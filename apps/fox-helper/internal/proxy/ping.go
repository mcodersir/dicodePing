package proxy

import (
	"context"
	"errors"
	"fmt"
	"net"
	"net/url"
	"sort"
	"strings"
	"sync"
	"time"

	"dicodeping/fox/internal/serverlist"
)

// FastestCountry is the proxy.country value that picks the location with
// the lowest measured latency at every engine start.
const FastestCountry = "fastest"

const (
	// PingTarget is reached through every location; Google answers close to
	// every exit, so the time mostly reflects the path to that exit.
	PingTarget = "www.google.com:443"

	pingAttempts = 2

	pingSessionTimeout = 12 * time.Second

	pingParallel = 8

	pingTotalLimit = 2 * time.Minute
)

// LocationPing is the latency of one location: the time a CONNECT to
// PingTarget takes through that location's proxy, on an already established
// session (best of pingAttempts).
//
// Every location's server is on Fastly's anycast network, so the handshake
// with the server reaches the same nearby Fastly edge for every location and
// says nothing about the location. A CONNECT travels on to the exit and back,
// which is the delay applications see.
type LocationPing struct {
	Code        string `json:"code"`
	Name        string `json:"name"`
	City        string `json:"city,omitempty"`
	Server      string `json:"server"`
	Recommended bool   `json:"recommended"`
	PingMS      int64  `json:"ping_ms,omitempty"`
	Error       string `json:"error,omitempty"`
}

func (p LocationPing) OK() bool { return p.Error == "" && p.PingMS > 0 }

// PingTargets returns one candidate per location, in server-list order.
func PingTargets(countries []serverlist.Country) []Candidate {
	seen := make(map[string]bool)
	var out []Candidate
	for _, candidate := range ConnectCandidates(countries) {
		code := strings.ToUpper(strings.TrimSpace(candidate.CountryCode))
		if code == "" || seen[code] {
			continue
		}
		seen[code] = true
		out = append(out, candidate)
	}
	return out
}

// pingMeter measures one location.
type pingMeter func(ctx context.Context, target Candidate) (time.Duration, error)

// pingSessionDialer opens a measurement session; tests replace it.
var pingSessionDialer = func(proxyURL *url.URL, token string, timeout time.Duration) (proxySession, error) {
	return dialH2ProxySession(proxyURL, token, timeout)
}

// TunnelMeter measures through a fresh HTTP/2 session per location, using
// the given proxy pass. Only the CONNECT round trips are timed.
func TunnelMeter(token string) pingMeter {
	return func(ctx context.Context, target Candidate) (time.Duration, error) {
		proxyURL, err := NormalizeURL(target.Addr)
		if err != nil {
			return 0, err
		}
		session, err := pingSessionDialer(proxyURL, token, pingSessionTimeout)
		if err != nil {
			return 0, err
		}
		defer session.Close()
		best := time.Duration(0)
		var lastErr error
		for attempt := 0; attempt < pingAttempts && ctx.Err() == nil; attempt++ {
			start := time.Now()
			conn, err := session.OpenTunnel(PingTarget)
			elapsed := time.Since(start)
			if err != nil {
				lastErr = err
				var connectErr *proxyConnectHTTPError
				if errors.As(err, &connectErr) {
					break // a refusal does not change on retry
				}
				continue
			}
			_ = conn.Close()
			if best == 0 || elapsed < best {
				best = elapsed
			}
		}
		if best > 0 {
			return best, nil
		}
		if lastErr == nil {
			lastErr = context.DeadlineExceeded
		}
		return 0, lastErr
	}
}

// PingLocations measures every target concurrently and returns the results
// sorted by latency, failed locations last.
func PingLocations(ctx context.Context, targets []Candidate, meter pingMeter) []LocationPing {
	ctx, cancel := context.WithTimeout(ctx, pingTotalLimit)
	defer cancel()
	results := make([]LocationPing, len(targets))
	limit := make(chan struct{}, pingParallel)
	var wg sync.WaitGroup
	for i, target := range targets {
		results[i] = LocationPing{
			Code:        strings.ToUpper(target.CountryCode),
			Name:        target.CountryName,
			City:        target.CityName,
			Server:      target.Addr,
			Recommended: target.IsRecommended(),
		}
		wg.Add(1)
		go func(i int, target Candidate) {
			defer wg.Done()
			select {
			case limit <- struct{}{}:
			case <-ctx.Done():
				results[i].Error = "timeout"
				return
			}
			defer func() { <-limit }()
			latency, err := meter(ctx, target)
			if err != nil {
				results[i].Error = pingErrorText(err)
				return
			}
			results[i].PingMS = max(1, latency.Milliseconds())
		}(i, target)
	}
	wg.Wait()
	sortPings(results)
	return results
}

func sortPings(results []LocationPing) {
	sort.SliceStable(results, func(i, j int) bool {
		a, b := results[i], results[j]
		if a.OK() != b.OK() {
			return a.OK()
		}
		if a.OK() && a.PingMS != b.PingMS {
			return a.PingMS < b.PingMS
		}
		return a.Name < b.Name
	})
}

func pingErrorText(err error) string {
	var connectErr *proxyConnectHTTPError
	if errors.As(err, &connectErr) {
		switch connectErr.statusCode {
		case 403:
			return "not allowed for this account"
		case 401, 407:
			return "proxy pass rejected"
		}
		return fmt.Sprintf("refused (HTTP %d)", connectErr.statusCode)
	}
	var dnsErr *net.DNSError
	switch {
	case errors.As(err, &dnsErr):
		return "DNS lookup failed"
	case errors.Is(err, context.DeadlineExceeded) || isTimeout(err):
		return "timeout"
	}
	return "unreachable"
}

func isTimeout(err error) bool {
	var netErr net.Error
	return errors.As(err, &netErr) && netErr.Timeout()
}

// FilterTargets keeps the targets whose country code is in codes.
func FilterTargets(targets []Candidate, codes []string) []Candidate {
	if len(codes) == 0 {
		return targets
	}
	wanted := make(map[string]bool, len(codes))
	for _, code := range codes {
		wanted[strings.ToUpper(strings.TrimSpace(code))] = true
	}
	var out []Candidate
	for _, target := range targets {
		if wanted[strings.ToUpper(target.CountryCode)] {
			out = append(out, target)
		}
	}
	return out
}

// MergePings replaces the measured locations in old and keeps the rest.
func MergePings(old, measured []LocationPing) []LocationPing {
	replaced := make(map[string]bool, len(measured))
	for _, p := range measured {
		replaced[p.Code] = true
	}
	merged := append([]LocationPing(nil), measured...)
	for _, p := range old {
		if !replaced[p.Code] {
			merged = append(merged, p)
		}
	}
	sortPings(merged)
	return merged
}

// FastestLocation picks the reachable location with the lowest latency,
// from every location in the server list, including those it marks locked.
// A location that failed the measurement is never picked.
func FastestLocation(results []LocationPing) (LocationPing, bool) {
	for _, r := range results {
		if r.OK() {
			return r, true
		}
	}
	return LocationPing{}, false
}
