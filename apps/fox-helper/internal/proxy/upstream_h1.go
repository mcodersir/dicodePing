package proxy

import (
	"bufio"
	"context"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"dicodeping/fox/internal/controlplane"
	"dicodeping/fox/internal/logx"
)

var errProxyHTTP1Unavailable = errors.New("proxy did not take HTTP/1.1")

// h1SpareAge is how long a spare connection is used for a tunnel: an idle
// TLS connection older than that may have been closed by the server.
const h1SpareAge = 20 * time.Second

// h1ProxySession is proxy.transport "h1": every tunnel is a TLS connection
// of its own to Mozilla's server carrying one HTTP/1.1 CONNECT, as a
// browser behind an HTTPS proxy does. Nothing is shared between tunnels, so
// a network that slows or cuts long connections cuts one tunnel, not all of
// them; each tunnel costs a TLS handshake (resumed where it can be), and one
// spare connection is kept ready to hide it. UDP keeps its own HTTP/2
// connection (udpUpstream), as with the other transports.
type h1ProxySession struct {
	proxyURL  *url.URL
	proxyHost string
	timeout   time.Duration
	tokenMu   sync.RWMutex
	token     string
	health    sessionFailureTracker

	mu      sync.Mutex
	closed  bool
	spare   net.Conn
	spareAt time.Time
	filling bool
	// tunnels are the open tunnels, closed with the session.
	tunnels map[net.Conn]struct{}
	alive   atomic.Bool
}

func newH1ProxySession(proxyURL *url.URL, token string, timeout time.Duration) (*h1ProxySession, error) {
	proxyHost := proxyURL.Host
	if proxyURL.Port() == "" {
		proxyHost = proxyURL.Hostname() + ":443"
	}
	s := &h1ProxySession{
		proxyURL:  proxyURL,
		proxyHost: proxyHost,
		timeout:   timeout,
		token:     token,
		tunnels:   make(map[net.Conn]struct{}),
	}
	// The first connection shows the server takes HTTP/1.1, and waits as
	// the spare for the first tunnel.
	conn, err := s.dial()
	if err != nil {
		return nil, err
	}
	s.spare, s.spareAt = conn, time.Now()
	s.alive.Store(true)
	logx.Info("upstream HTTP/1.1 connection established proxy=%s", proxyHost)
	return s, nil
}

// dial opens a TLS connection to the server, for HTTP/1.1.
func (s *h1ProxySession) dial() (net.Conn, error) {
	ctx, cancel := context.Background(), context.CancelFunc(func() {})
	if s.timeout > 0 {
		ctx, cancel = context.WithTimeout(context.Background(), s.timeout)
	}
	defer cancel()
	conn, _, err := dialUpstreamTLSFor(ctx, s.proxyURL, s.proxyHost, alpnH1)
	return conn, err
}

// takeSpare hands the spare connection over when it is fresh, and starts
// another one.
func (s *h1ProxySession) takeSpare() net.Conn {
	s.mu.Lock()
	defer s.mu.Unlock()
	conn := s.spare
	s.spare = nil
	if conn != nil && time.Since(s.spareAt) > h1SpareAge {
		conn.Close()
		conn = nil
	}
	if !s.closed && !s.filling {
		s.filling = true
		go s.fillSpare()
	}
	return conn
}

func (s *h1ProxySession) fillSpare() {
	conn, err := s.dial()
	s.mu.Lock()
	defer s.mu.Unlock()
	s.filling = false
	if err != nil {
		return
	}
	if s.closed || s.spare != nil {
		conn.Close()
		return
	}
	s.spare, s.spareAt = conn, time.Now()
}

func (s *h1ProxySession) OpenTunnel(authority string) (net.Conn, error) {
	if s.isClosed() {
		return nil, ErrNoUsableSession
	}
	// A spare the server closed while it waited fails before any answer:
	// a fresh connection is tried then.
	if spare := s.takeSpare(); spare != nil {
		conn, answered, err := s.connect(spare, authority)
		if err == nil || answered {
			return conn, s.health.observe(authority, err)
		}
	}
	raw, err := s.dial()
	if err != nil {
		return nil, s.health.observe(authority, err)
	}
	conn, _, err := s.connect(raw, authority)
	return conn, s.health.observe(authority, err)
}

// connect sends a CONNECT for authority on raw and reads the answer;
// answered says the server answered, so another connection would not do
// better.
func (s *h1ProxySession) connect(raw net.Conn, authority string) (conn net.Conn, answered bool, err error) {
	if s.timeout > 0 {
		_ = raw.SetDeadline(time.Now().Add(s.timeout))
	}
	request := "CONNECT " + authority + " HTTP/1.1\r\n" +
		"Host: " + authority + "\r\n" +
		"Proxy-Authorization: Bearer " + s.bearerToken() + "\r\n" +
		// As Firefox's CONNECT.
		"User-Agent: " + controlplane.FirefoxUserAgent() + "\r\n\r\n"
	if _, err := io.WriteString(raw, request); err != nil {
		raw.Close()
		return nil, false, s.openError(err)
	}
	br := bufio.NewReader(raw)
	resp, err := http.ReadResponse(br, &http.Request{Method: http.MethodConnect})
	if err != nil {
		raw.Close()
		return nil, false, s.openError(err)
	}
	if resp.StatusCode < 200 || resp.StatusCode > 299 {
		body, _ := io.ReadAll(io.LimitReader(resp.Body, 2048))
		resp.Body.Close()
		raw.Close()
		return nil, true, &proxyConnectHTTPError{
			statusCode: resp.StatusCode,
			status:     resp.Status,
			body:       strings.TrimSpace(string(body)),
		}
	}
	_ = raw.SetDeadline(time.Time{})
	tunnel := &h1Tunnel{Conn: raw, r: br, session: s}
	if !s.track(tunnel) {
		raw.Close()
		return nil, true, ErrNoUsableSession
	}
	return tunnel, true, nil
}

// openError is a CONNECT that got no answer: a timeout reads as the other
// transports' open timeout, which the session's health counts.
func (s *h1ProxySession) openError(err error) error {
	if errors.Is(err, os.ErrDeadlineExceeded) {
		return &tunnelOpenTimeoutError{timeout: s.timeout}
	}
	return fmt.Errorf("proxy CONNECT over HTTP/1.1: %w", err)
}

func (s *h1ProxySession) track(t *h1Tunnel) bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.closed {
		return false
	}
	s.tunnels[t] = struct{}{}
	return true
}

func (s *h1ProxySession) untrack(t *h1Tunnel) {
	s.mu.Lock()
	delete(s.tunnels, t)
	s.mu.Unlock()
}

func (s *h1ProxySession) isClosed() bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.closed
}

// IsAlive is true until Close: the session holds no connection whose loss
// would end it.
func (s *h1ProxySession) IsAlive() bool { return s.alive.Load() }

func (s *h1ProxySession) bearerToken() string {
	s.tokenMu.RLock()
	defer s.tokenMu.RUnlock()
	return s.token
}

func (s *h1ProxySession) UpdateToken(token string) error {
	if strings.TrimSpace(token) == "" {
		return fmt.Errorf("empty proxy session token")
	}
	s.tokenMu.Lock()
	s.token = token
	s.tokenMu.Unlock()
	return nil
}

// Close ends the session's tunnels and its spare connection, as closing an
// HTTP/2 session ends its streams.
func (s *h1ProxySession) Close() error {
	s.mu.Lock()
	if s.closed {
		s.mu.Unlock()
		return nil
	}
	s.closed = true
	s.alive.Store(false)
	spare := s.spare
	s.spare = nil
	tunnels := make([]net.Conn, 0, len(s.tunnels))
	for t := range s.tunnels {
		tunnels = append(tunnels, t)
	}
	s.mu.Unlock()
	if spare != nil {
		spare.Close()
	}
	for _, t := range tunnels {
		t.Close()
	}
	return nil
}

// h1Tunnel is a CONNECT tunnel over its own TLS connection; r holds what
// the server sent after its answer.
type h1Tunnel struct {
	net.Conn
	r       *bufio.Reader
	session *h1ProxySession
	once    sync.Once
}

func (t *h1Tunnel) Read(p []byte) (int, error) { return t.r.Read(p) }

func (t *h1Tunnel) Close() error {
	err := t.Conn.Close()
	t.once.Do(func() { t.session.untrack(t) })
	return err
}
