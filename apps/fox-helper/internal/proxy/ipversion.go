package proxy

import (
	"context"
	"fmt"
	"net"
	"net/netip"
	"sync/atomic"
	"time"

	"dicodeping/fox/internal/logx"
	"dicodeping/fox/internal/resolver"
)

// proxy.ip_version, for the connections to Mozilla's servers alone (the
// sign-in, the DNS, and the API keep their own way):
//
//   - "auto" (the default; empty too): IPv4 first, IPv6 when no IPv4
//     address connects;
//   - "dual": both at once, IPv4 and IPv6 addresses tried interleaved, the
//     first to connect taken (dual-stack, Happy Eyeballs);
//   - "ipv6_first": IPv6 first, IPv4 when no IPv6 address connects;
//   - "ipv4", "ipv6": that version alone.
var upstreamIPVersion atomic.Pointer[string]

// SetUpstreamIPVersion sets proxy.ip_version for the connections made from
// now on.
func SetUpstreamIPVersion(v string) { upstreamIPVersion.Store(&v) }

// IP versions of a step: one of them, or both at once.
const (
	stepIPv4 = "4"
	stepIPv6 = "6"
	stepBoth = "46"
)

// upstreamSteps is proxy.ip_version as the IP versions to try, in turn.
func upstreamSteps() []string {
	v := ""
	if p := upstreamIPVersion.Load(); p != nil {
		v = *p
	}
	switch v {
	case "ipv4":
		return []string{stepIPv4}
	case "ipv6":
		return []string{stepIPv6}
	case "ipv6_first":
		return []string{stepIPv6, stepIPv4}
	case "dual":
		return []string{stepBoth}
	default:
		return []string{stepIPv4, stepIPv6}
	}
}

// stepContext is ctx for a step: one that another follows gets half the
// time left (15 s without a deadline), so that the next one has time too
// where this one's addresses do not even answer.
func stepContext(ctx context.Context, i int, steps []string) (context.Context, context.CancelFunc) {
	if i == len(steps)-1 {
		return ctx, func() {}
	}
	if deadline, ok := ctx.Deadline(); ok {
		return context.WithTimeout(ctx, time.Until(deadline)/2)
	}
	return context.WithTimeout(ctx, 15*time.Second)
}

// stepError keeps the error worth showing of a connection's steps: the
// IPv4 one when there was one (IPv6 mostly fails only for want of it).
type stepError struct{ first, v4 error }

func (e *stepError) note(step string, err error) {
	if e.first == nil {
		e.first = err
	}
	if step != stepIPv6 && e.v4 == nil {
		e.v4 = err
	}
}

func (e *stepError) err() error {
	if e.v4 != nil {
		return e.v4
	}
	return e.first
}

func stepName(step string) string {
	switch step {
	case stepIPv4:
		return "IPv4"
	case stepIPv6:
		return "IPv6"
	}
	return "IPv4 and IPv6"
}

// dialUpstream connects to a Mozilla server over TCP in proxy.ip_version.
// Through the user's own SOCKS5 proxy, which picks the address itself, the
// version is the proxy's.
func dialUpstream(ctx context.Context, address string) (net.Conn, error) {
	if resolver.UpstreamProxy() != "" {
		return resolver.Dial(ctx, "tcp", address)
	}
	steps := upstreamSteps()
	var failed stepError
	for i, step := range steps {
		stepCtx, cancel := stepContext(ctx, i, steps)
		var conn net.Conn
		var err error
		switch step {
		case stepIPv4:
			conn, err = resolver.Dial(stepCtx, "tcp4", address)
		case stepIPv6:
			conn, err = resolver.Dial(stepCtx, "tcp6", address)
		default:
			conn, err = resolver.DialBoth(stepCtx, address)
		}
		cancel()
		if err == nil {
			if i > 0 {
				logx.Info("Mozilla's server answered over %s after %s failed proxy=%s err=%s", stepName(step), stepName(steps[0]), address, logx.Err(failed.first))
			}
			return conn, nil
		}
		failed.note(step, err)
		if ctx.Err() != nil {
			break
		}
	}
	return nil, failed.err()
}

// upstreamAddrs looks host up for a step: its IPv4 or IPv6 addresses, or
// both interleaved.
func upstreamAddrs(ctx context.Context, host, step string) ([]netip.Addr, error) {
	switch step {
	case stepIPv4:
		return resolver.LookupNetIPFamily(ctx, host, "udp4")
	case stepIPv6:
		return resolver.LookupNetIPFamily(ctx, host, "udp6")
	}
	return resolver.LookupNetIPBoth(ctx, host)
}

// noAddrsError is a step's lookup that found no address of its version.
func noAddrsError(host, step string) error {
	return fmt.Errorf("%s has no %s address", host, stepName(step))
}
