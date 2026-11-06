// Package controlplane owns the shared HTTP client for every control-plane
// API request (Firefox Accounts, Guardian, Remote Settings). It is kept
// separate from the data-plane CONNECT sessions and from http.DefaultClient.
package controlplane

import (
	"context"
	"crypto/tls"
	"crypto/x509"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/http/cookiejar"
	"net/url"
	"sync/atomic"
	"time"

	utls "github.com/refraction-networking/utls"
	"golang.org/x/net/http2"

	"dicodeping/fox/internal/firefoxtls"
	"dicodeping/fox/internal/hellosplit"
	"dicodeping/fox/internal/resolver"
)

const (
	clientTimeout      = 30 * time.Second
	dialTimeout        = 30 * time.Second
	handshakeTimeout   = 10 * time.Second
	directHTTP2Timeout = 8 * time.Second
	errorBodyLogLimit  = 16 * 1024
)

// defaultTransport is Go's default transport with its connections resolved
// through the configured DNS servers (package resolver), and without
// HTTP_PROXY and HTTPS_PROXY: another program's proxy left in the
// environment (v2rayN's 127.0.0.1:10808), not running, refused every
// sign-in and Guardian request, which then read as Mozilla being blocked.
// The user's own relay is network.api_relay. Its TLS starts with
// Firefox's hello (firefoxTLS).
var defaultTransport = func() *http.Transport {
	t := http.DefaultTransport.(*http.Transport).Clone()
	t.Proxy = nil
	t.DialContext = DialContext
	t.DialTLSContext = firefoxTLS(DialContext, handshakeTimeout)
	return t
}()

// QuickTransport is the default transport that gives up on a server it
// cannot connect to within wait (the connection and TLS each; the name has
// its own time, resolver.DialWithin): the user's relay is tried then
// (service.relayFallback), rather than waiting for the default's half a
// minute.
func QuickTransport(wait time.Duration) *http.Transport {
	t := defaultTransport.Clone()
	t.DialContext = func(ctx context.Context, network, address string) (net.Conn, error) {
		ctx, cancel := context.WithTimeout(ctx, dialTimeout)
		defer cancel()
		conn, err := resolver.DialWithin(ctx, wait, network, address)
		if err != nil {
			return nil, err
		}
		return hellosplit.Wrap(conn), nil
	}
	t.DialTLSContext = firefoxTLS(t.DialContext, wait)
	t.TLSHandshakeTimeout = wait
	return t
}

// firefoxSessions lets a new connection to a server resume its TLS session.
var trustRoots atomic.Pointer[x509.CertPool]

func SetRoots(roots *x509.CertPool) { trustRoots.Store(roots) }

var firefoxSessions = utls.NewLRUClientSessionCache(64)

// firefoxTLS connects with connect and completes TLS with desktop Firefox's
// hello within wait, the way to Mozilla's servers looking like the Firefox
// the User-Agent names (package firefoxtls). It offers HTTP/1.1 alone:
// net/http speaks HTTP/2 only over its own TLS.
func firefoxTLS(connect func(ctx context.Context, network, address string) (net.Conn, error), wait time.Duration) func(ctx context.Context, network, address string) (net.Conn, error) {
	return func(ctx context.Context, network, address string) (net.Conn, error) {
		conn, err := dialFirefoxTLS(ctx, network, address, connect, wait, firefoxSessions, "http/1.1")
		if err != nil {
			return nil, err
		}
		return conn, nil
	}
}

func dialFirefoxTLS(ctx context.Context, network, address string, connect func(context.Context, string, string) (net.Conn, error), wait time.Duration, sessions utls.ClientSessionCache, alpn ...string) (*utls.UConn, error) {
	host, _, err := net.SplitHostPort(address)
	if err != nil {
		return nil, err
	}
	raw, err := connect(ctx, network, address)
	if err != nil {
		return nil, err
	}
	shakeCtx, cancel := context.WithTimeout(ctx, wait)
	defer cancel()
	conn, err := firefoxtls.Handshake(shakeCtx, raw, host, trustRoots.Load(), sessions, alpn...)
	if err != nil {
		raw.Close()
		return nil, err
	}
	return conn, nil
}

// DialContext connects through the configured resolver with a timeout; a
// custom transport (the API proxy) uses it to reach its proxy.
func DialContext(ctx context.Context, network, address string) (net.Conn, error) {
	ctx, cancel := context.WithTimeout(ctx, dialTimeout)
	defer cancel()
	return dial(ctx, network, address)
}

// dial connects through the configured resolver, the TLS over it sending
// its ClientHello as network.hello_split says: the filter that stops the
// VPN's servers may stop these names too.
func dial(ctx context.Context, network, address string) (net.Conn, error) {
	conn, err := resolver.Dial(ctx, network, address)
	if err != nil {
		return nil, err
	}
	return hellosplit.Wrap(conn), nil
}

// client carries an explicit timeout so requests can never hang
// indefinitely; SetTransport may replace its Transport. Its cookie jar holds
// the Fastly anti-bot challenge cookies earned by the FxA challenge solver.
var client = func() *http.Client {
	jar, err := cookiejar.New(nil)
	if err != nil {
		panic(fmt.Sprintf("creating control plane cookie jar: %v", err))
	}
	return &http.Client{
		Timeout:   clientTimeout,
		Jar:       jar,
		Transport: defaultTransport,
	}
}()

var directHTTP2Client = &http.Client{
	Jar:     client.Jar,
	Timeout: directHTTP2Timeout,
	Transport: &http2.Transport{
		IdleConnTimeout: clientTimeout,
		DialTLSContext: func(ctx context.Context, network, address string, _ *tls.Config) (net.Conn, error) {
			// Keep HTTP/1.1's TLS session cache separate from this probe.
			conn, err := dialFirefoxTLS(ctx, network, address, DialContext, handshakeTimeout, nil, "h2", "http/1.1")
			if err != nil {
				return nil, err
			}
			if conn.ConnectionState().NegotiatedProtocol != "h2" {
				conn.Close()
				return nil, errors.New("server did not negotiate HTTP/2")
			}
			return conn, nil
		},
	},
	CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse },
}

// ErrDirectHTTP2Unavailable indicates that the configured transport must be used.
var ErrDirectHTTP2Unavailable = errors.New("direct HTTP/2 unavailable with a custom control plane transport")

// DoDirectHTTP2 sends a short HTTP/2 probe with the shared cookie jar. It
// is available only on the default route so it cannot skip a configured
// API relay. The response body remains readable until the request deadline.
func DoDirectHTTP2(req *http.Request) (*http.Response, error) {
	if client.Transport != defaultTransport {
		return nil, ErrDirectHTTP2Unavailable
	}
	return directHTTP2Client.Do(req)
}

// SetTransport routes Firefox Accounts, Guardian, and Remote Settings
// requests through transport (nil restores the default transport). It must
// be called before any control plane request is issued, because the client
// is shared process-wide.
func SetTransport(transport http.RoundTripper) {
	if transport == nil {
		transport = defaultTransport
	}
	client.Transport = transport
}

// Transport returns the configured transport.
func Transport() http.RoundTripper {
	return client.Transport
}

// Do sends req with the shared control plane client.
func Do(req *http.Request) (*http.Response, error) {
	return client.Do(req)
}

// SetCookies stores cookies for u in the shared client's cookie jar.
func SetCookies(u *url.URL, cookies []*http.Cookie) {
	client.Jar.SetCookies(u, cookies)
}

// ReadErrorBody reads a bounded prefix of an error response body for
// diagnostics.
func ReadErrorBody(r io.Reader) string {
	body, err := io.ReadAll(io.LimitReader(r, errorBodyLogLimit))
	if err != nil {
		return "reading error body failed: " + err.Error()
	}
	return string(body)
}
