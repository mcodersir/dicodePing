package proxy

import (
	"context"
	"crypto/tls"
	"errors"
	"net"
	"net/url"
	"sync/atomic"
	"time"

	utls "github.com/refraction-networking/utls"

	"dicodeping/fox/internal/firefoxtls"
	"dicodeping/fox/internal/hellosplit"
	"dicodeping/fox/internal/logx"
	"dicodeping/fox/internal/resolver"
)

var (
	// upstreamTLSSessions and upstreamFirefoxSessions let a new connection to a
	// server resume TLS, which saves the time of a whole handshake when the
	// network cuts connections and the program reconnects.
	upstreamTLSSessions     = tls.NewLRUClientSessionCache(32)
	upstreamFirefoxSessions = utls.NewLRUClientSessionCache(32)

	// upstreamGoTLS is set once Firefox's hello failed where Go's passed: a
	// network or server that takes only Go's gets it without another failure
	// on each new connection, until the program restarts.
	upstreamGoTLS atomic.Bool
)

// firefoxHandshakeShare is how much of the time left the Firefox hello may
// use, leaving the rest to Go's for a network that drops it silently.
const firefoxHandshakeShare = 2

// firefoxHandshake completes TLS on raw with Firefox's hello.
func firefoxHandshake(ctx context.Context, raw net.Conn, name string) (net.Conn, error) {
	conn, err := firefoxtls.Handshake(ctx, raw, name, upstreamRoots.Load(), upstreamFirefoxSessions, "h2", "http/1.1")
	if err != nil {
		return nil, err
	}
	if conn.ConnectionState().NegotiatedProtocol != "h2" {
		return nil, errProxyHTTP2Unavailable
	}
	return conn, nil
}

// goHandshake completes TLS on raw with Go's own hello.
func goHandshake(ctx context.Context, raw net.Conn, name string) (net.Conn, error) {
	conn := tls.Client(raw, &tls.Config{
		RootCAs:            upstreamRoots.Load(),
		ServerName:         name,
		MinVersion:         tls.VersionTLS12,
		NextProtos:         []string{"h2"},
		ClientSessionCache: upstreamTLSSessions,
	})
	if err := conn.HandshakeContext(ctx); err != nil {
		return nil, err
	}
	if conn.ConnectionState().NegotiatedProtocol != "h2" {
		return nil, errProxyHTTP2Unavailable
	}
	return conn, nil
}

// firefoxContext limits ctx to the share of its time the Firefox hello may use.
func firefoxContext(ctx context.Context) (context.Context, context.CancelFunc) {
	deadline, ok := ctx.Deadline()
	if !ok {
		return context.WithCancel(ctx)
	}
	return context.WithTimeout(ctx, time.Until(deadline)/firefoxHandshakeShare)
}

// upstreamHandshakeError marks a failure of TLS itself, which another hello may
// get past; a failure to connect is not one.
type upstreamHandshakeError struct{ err error }

func (e *upstreamHandshakeError) Error() string { return e.err.Error() }
func (e *upstreamHandshakeError) Unwrap() error { return e.err }

// upstreamHandshake connects to proxyHost and completes TLS with shake.
func upstreamHandshake(ctx context.Context, proxyHost, name string, shake func(context.Context, net.Conn, string) (net.Conn, error)) (net.Conn, *watchedConn, error) {
	dialed, err := resolver.Dial(ctx, "tcp", proxyHost)
	if err != nil {
		return nil, nil, err
	}
	raw := newWatchedConn(hellosplit.Wrap(dialed))
	conn, err := shake(ctx, raw, name)
	if err != nil {
		_ = raw.Close()
		if errors.Is(err, errProxyHTTP2Unavailable) {
			return nil, nil, err
		}
		return nil, nil, &upstreamHandshakeError{err}
	}
	return conn, raw, nil
}

// dialUpstreamTLS connects to proxyHost and completes TLS with proxyURL's name,
// for HTTP/2. It looks like the Firefox its User-Agent says it is; a handshake
// that fails that way is tried again with Go's hello.
func dialUpstreamTLS(ctx context.Context, proxyURL *url.URL, proxyHost string) (net.Conn, *watchedConn, error) {
	name := proxyURL.Hostname()
	if upstreamGoTLS.Load() {
		return upstreamHandshake(ctx, proxyHost, name, goHandshake)
	}
	firstCtx, cancel := firefoxContext(ctx)
	defer cancel()
	conn, raw, err := upstreamHandshake(firstCtx, proxyHost, name, firefoxHandshake)
	var failed *upstreamHandshakeError
	if err == nil || ctx.Err() != nil || !errors.As(err, &failed) {
		return conn, raw, err
	}
	logx.Warn("upstream TLS with Firefox's hello failed; trying Go's proxy=%s err=%s", proxyHost, logx.Err(err))
	conn, raw, err = upstreamHandshake(ctx, proxyHost, name, goHandshake)
	if err == nil {
		upstreamGoTLS.Store(true)
	}
	return conn, raw, err
}
