package resolver

import (
	"context"
	"crypto/rand"
	"encoding/binary"
	"errors"
	"fmt"
	"io"
	"net"
	"strings"
	"sync"
	"time"

	"golang.org/x/net/dns/dnsmessage"
)

// ErrNoECH means that the name's DNS has no ECH key: no HTTPS record, or
// one without the ech parameter.
var ErrNoECH = errors.New("no ECH key in its DNS")

// echFallbackSpecs are asked for ECH keys besides the configured servers.
// Plain DNS is among them: a network that blocks encrypted DNS often lets
// it through. A forged key cannot pass a wrong server: the handshake then
// fails, and the certificate is checked as always.
var echFallbackSpecs = []string{
	"https://1.1.1.1/dns-query",
	"https://8.8.8.8/dns-query",
	"udp://1.1.1.1",
	"udp://8.8.8.8",
}

// echFallback builds the servers of echFallbackSpecs once; tests replace
// it.
var echFallback = sync.OnceValue(func() []server {
	var out []server
	for _, spec := range echFallbackSpecs {
		if s, err := parseServer(spec); err == nil {
			out = append(out, s)
		}
	}
	return out
})

// LookupECH returns the ECH key (an ECHConfigList) in the HTTPS DNS record
// of host, and the record's TTL, through the installed resolver.
func LookupECH(ctx context.Context, host string) ([]byte, time.Duration, error) {
	return Current().LookupECH(ctx, host)
}

// LookupECH asks the resolver's servers and the fallback ones at once for
// host's HTTPS record; the first answer with a key wins. Every server
// saying that there is none is ErrNoECH. Keys are not cached here: the
// caller keeps one for its TTL.
func (r *Resolver) LookupECH(ctx context.Context, host string) ([]byte, time.Duration, error) {
	host = strings.TrimSuffix(strings.ToLower(strings.TrimSpace(host)), ".")
	query, err := httpsQuery(host)
	if err != nil {
		return nil, 0, err
	}
	servers := r.echServers()
	ctx, cancel := context.WithTimeout(ctx, queryTimeout)
	defer cancel()
	type answer struct {
		key    []byte
		ttl    time.Duration
		source string
		err    error
	}
	answers := make(chan answer, len(servers))
	for _, s := range servers {
		go func(s server) {
			reply, err := s.exchange(ctx, query)
			var a answer
			if err == nil {
				a.key, a.ttl, err = parseECH(reply)
			}
			a.source, a.err = s.String(), err
			answers <- a
		}(s)
	}
	var errs serverErrors
	for range servers {
		a := <-answers
		if a.err == nil {
			return a.key, a.ttl, nil
		}
		errs = append(errs, fmt.Errorf("%s: %w", a.source, a.err))
	}
	return nil, 0, fmt.Errorf("ECH key of %s: %w", host, errs)
}

// echServers are the configured servers and the fallback ones, each once.
func (r *Resolver) echServers() []server {
	var out []server
	seen := map[string]bool{}
	add := func(s server) {
		if !seen[s.String()] {
			seen[s.String()] = true
			out = append(out, s)
		}
	}
	if r != nil {
		for _, s := range r.servers {
			add(s)
		}
	}
	for _, s := range echFallback() {
		add(s)
	}
	return out
}

// httpsQuery asks for host's HTTPS record, with room for a large answer
// over UDP (EDNS0).
func httpsQuery(host string) ([]byte, error) {
	name, err := dnsmessage.NewName(host + ".")
	if err != nil {
		return nil, err
	}
	var id [2]byte
	_, _ = rand.Read(id[:])
	var opt dnsmessage.ResourceHeader
	if err := opt.SetEDNS0(1232, dnsmessage.RCodeSuccess, false); err != nil {
		return nil, err
	}
	msg := dnsmessage.Message{
		Header:      dnsmessage.Header{ID: binary.BigEndian.Uint16(id[:]), RecursionDesired: true},
		Questions:   []dnsmessage.Question{{Name: name, Type: dnsmessage.TypeHTTPS, Class: dnsmessage.ClassINET}},
		Additionals: []dnsmessage.Resource{{Header: opt, Body: &dnsmessage.OPTResource{}}},
	}
	return msg.Pack()
}

// parseECH returns the ech parameter of the first HTTPS record that has
// one, and that record's TTL; CNAME chains are followed by the server.
func parseECH(reply []byte) ([]byte, time.Duration, error) {
	var p dnsmessage.Parser
	header, err := p.Start(reply)
	if err != nil {
		return nil, 0, err
	}
	if header.RCode != dnsmessage.RCodeSuccess {
		return nil, 0, fmt.Errorf("DNS error %s", header.RCode)
	}
	if err := p.SkipAllQuestions(); err != nil {
		return nil, 0, err
	}
	for {
		h, err := p.AnswerHeader()
		if errors.Is(err, dnsmessage.ErrSectionDone) {
			return nil, 0, ErrNoECH
		}
		if err != nil {
			return nil, 0, err
		}
		if h.Type != dnsmessage.TypeHTTPS {
			if err := p.SkipAnswer(); err != nil {
				return nil, 0, err
			}
			continue
		}
		r, err := p.HTTPSResource()
		if err != nil {
			return nil, 0, err
		}
		if key, ok := r.GetParam(dnsmessage.SVCParamECH); ok && len(key) > 0 {
			return key, time.Duration(h.TTL) * time.Second, nil
		}
	}
}

// exchange sends a DNS message and returns the reply as it is: over UDP
// (again over TCP when the reply is truncated), TCP, or TLS.
func (s *streamServer) exchange(ctx context.Context, msg []byte) ([]byte, error) {
	if s.kind == "udp" {
		reply, err := s.exchangeUDP(ctx, msg)
		if err != nil || reply[2]&0x02 == 0 {
			return reply, err
		}
	}
	conn, err := s.dial(ctx, "tcp")
	if err != nil {
		return nil, err
	}
	defer conn.Close()
	setDeadline(ctx, conn)
	framed := binary.BigEndian.AppendUint16(nil, uint16(len(msg)))
	if _, err := conn.Write(append(framed, msg...)); err != nil {
		return nil, err
	}
	var size [2]byte
	if _, err := io.ReadFull(conn, size[:]); err != nil {
		return nil, err
	}
	reply := make([]byte, binary.BigEndian.Uint16(size[:]))
	if _, err := io.ReadFull(conn, reply); err != nil {
		return nil, err
	}
	return reply, nil
}

// exchangeUDP sends msg in one datagram and waits for the reply with the
// same ID (at least a header long).
func (s *streamServer) exchangeUDP(ctx context.Context, msg []byte) ([]byte, error) {
	conn, err := s.dial(ctx, "udp")
	if err != nil {
		return nil, err
	}
	defer conn.Close()
	setDeadline(ctx, conn)
	if _, err := conn.Write(msg); err != nil {
		return nil, err
	}
	buf := make([]byte, 4096)
	for {
		n, err := conn.Read(buf)
		if err != nil {
			return nil, err
		}
		if n >= 12 && buf[0] == msg[0] && buf[1] == msg[1] {
			return buf[:n], nil
		}
	}
}

func setDeadline(ctx context.Context, conn net.Conn) {
	if deadline, ok := ctx.Deadline(); ok {
		_ = conn.SetDeadline(deadline)
	}
}
