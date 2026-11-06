package resolver

import (
	"context"
	"crypto/tls"
	"errors"
	"fmt"
	"net"
	"net/http"
	"time"
)

// ThroughServers are the DNS-over-HTTPS servers NewThrough asks, by IP
// address so no lookup is needed to reach them; their certificates name
// these addresses.
var ThroughServers = []string{"https://1.1.1.1/dns-query", "https://8.8.8.8/dns-query"}

// DialFunc opens a connection, such as a tunnel through Mozilla's proxy.
type DialFunc func(ctx context.Context, network, address string) (net.Conn, error)

// throughClient builds the HTTP client of NewThrough; tests replace it to
// trust a local server.
var throughClient = func(dial DialFunc) *http.Client {
	return &http.Client{
		Timeout: queryTimeout,
		Transport: &http.Transport{
			Proxy:               nil,
			DialContext:         dial,
			TLSClientConfig:     &tls.Config{MinVersion: tls.VersionTLS12},
			ForceAttemptHTTP2:   true,
			TLSHandshakeTimeout: queryTimeout,
			MaxIdleConns:        2,
			// An idle connection is a tunnel that keeps the proxy in use;
			// close it well before the proxy would sleep.
			IdleConnTimeout: time.Minute,
		},
	}
}

// NewThrough returns a resolver that asks ThroughServers over connections
// from dial. It never falls back to the system resolver: on a filtered
// network that resolver answers blocked names with the address of a block
// page. Answers are cached like those of New.
func NewThrough(dial DialFunc) *Resolver {
	client := throughClient(dial)
	r := &Resolver{cache: make(map[string]cacheEntry)}
	for _, u := range ThroughServers {
		r.servers = append(r.servers, &dohServer{url: u, client: client})
	}
	return r
}

// Exchange sends a whole DNS query in wire format to every DNS-over-HTTPS
// server at once and returns the first answer as it is, for DNS a client
// sends through the proxy (Mozilla does not connect to port 53). Servers
// of other kinds are not asked.
func (r *Resolver) Exchange(ctx context.Context, query []byte) ([]byte, error) {
	var servers []*dohServer
	if r != nil {
		for _, s := range r.servers {
			if d, ok := s.(*dohServer); ok {
				servers = append(servers, d)
			}
		}
	}
	if len(servers) == 0 {
		return nil, errors.New("no DNS-over-HTTPS server to ask")
	}
	ctx, cancel := context.WithTimeout(ctx, queryTimeout)
	defer cancel()
	type answer struct {
		msg    []byte
		source string
		err    error
	}
	answers := make(chan answer, len(servers))
	for _, s := range servers {
		go func() {
			msg, err := s.exchange(ctx, query)
			answers <- answer{msg, s.String(), err}
		}()
	}
	var errs serverErrors
	for range servers {
		a := <-answers
		if a.err == nil {
			return a.msg, nil
		}
		errs = append(errs, fmt.Errorf("%s: %w", a.source, a.err))
	}
	return nil, fmt.Errorf("asking DNS over HTTPS failed: %w", errs)
}
