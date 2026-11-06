package proxy

import (
	"encoding/base64"
	"fmt"
	"io"
	"net"
	"net/http"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"dicodeping/fox/internal/controlplane"
	"dicodeping/fox/internal/serverlist"
)

type delayedTunnelOpener struct {
	started chan struct{}
	release chan struct{}
	conn    net.Conn
}

func init() {
	// Background device registration must never reach the real FxA from a
	// test; the tests that cover it enable it with a mock transport.
	DeviceRegistration.Store(false)
}

func (d *delayedTunnelOpener) OpenTunnel(string) (net.Conn, error) {
	close(d.started)
	<-d.release
	return d.conn, nil
}

type closeTrackingConn struct {
	net.Conn
	closed atomic.Bool
}

func (c *closeTrackingConn) Close() error {
	c.closed.Store(true)
	return c.Conn.Close()
}

type fakeTunnelOpener struct {
	active atomic.Int32
	max    atomic.Int32
	delay  time.Duration
}

func (f *fakeTunnelOpener) OpenTunnel(authority string) (net.Conn, error) {
	current := f.active.Add(1)
	for {
		max := f.max.Load()
		if current <= max || f.max.CompareAndSwap(max, current) {
			break
		}
	}

	left, right := net.Pipe()
	go func() {
		time.Sleep(f.delay)
		f.active.Add(-1)
		_ = right.Close()
	}()
	return left, nil
}

type fakeProxySession struct {
	openCount   atomic.Int32
	closeCount  atomic.Int32
	updateCount atomic.Int32
	openErr     error
	updateErr   error
	tokenMu     sync.Mutex
	token       string
}

// mortalProxySession is a fake session that can report itself dead, standing in
// for a session whose keepalive PING has failed.
type mortalProxySession struct {
	fakeProxySession
	alive atomic.Bool
}

func newMortalProxySession() *mortalProxySession {
	s := &mortalProxySession{}
	s.alive.Store(true)
	return s
}

func (s *mortalProxySession) IsAlive() bool { return s.alive.Load() }

func (s *fakeProxySession) OpenTunnel(authority string) (net.Conn, error) {
	s.openCount.Add(1)
	if s.openErr != nil {
		return nil, s.openErr
	}
	return &fakeNetConn{}, nil
}

func (s *fakeProxySession) Close() error {
	s.closeCount.Add(1)
	return nil
}

func (s *fakeProxySession) UpdateToken(token string) error {
	s.updateCount.Add(1)
	if s.updateErr != nil {
		return s.updateErr
	}
	s.tokenMu.Lock()
	s.token = token
	s.tokenMu.Unlock()
	return nil
}

func (s *fakeProxySession) currentToken() string {
	s.tokenMu.Lock()
	defer s.tokenMu.Unlock()
	return s.token
}

type fakeNetConn struct{}

func (c *fakeNetConn) Read(p []byte) (int, error)       { return 0, io.EOF }
func (c *fakeNetConn) Write(p []byte) (int, error)      { return len(p), nil }
func (c *fakeNetConn) Close() error                     { return nil }
func (c *fakeNetConn) LocalAddr() net.Addr              { return tunnelAddr("fake") }
func (c *fakeNetConn) RemoteAddr() net.Addr             { return tunnelAddr("fake") }
func (c *fakeNetConn) SetDeadline(time.Time) error      { return nil }
func (c *fakeNetConn) SetReadDeadline(time.Time) error  { return nil }
func (c *fakeNetConn) SetWriteDeadline(time.Time) error { return nil }

type controlledNetConn struct {
	readErr error
	closed  chan struct{}
	once    sync.Once
}

func newControlledNetConn(readErr error) *controlledNetConn {
	return &controlledNetConn{readErr: readErr, closed: make(chan struct{})}
}

func (c *controlledNetConn) Read([]byte) (int, error) {
	if c.readErr != nil {
		return 0, c.readErr
	}
	<-c.closed
	return 0, net.ErrClosed
}

func (c *controlledNetConn) Write(p []byte) (int, error) { return len(p), nil }
func (c *controlledNetConn) Close() error {
	c.once.Do(func() { close(c.closed) })
	return nil
}
func (c *controlledNetConn) LocalAddr() net.Addr              { return tunnelAddr("controlled") }
func (c *controlledNetConn) RemoteAddr() net.Addr             { return tunnelAddr("controlled") }
func (c *controlledNetConn) SetDeadline(time.Time) error      { return nil }
func (c *controlledNetConn) SetReadDeadline(time.Time) error  { return nil }
func (c *controlledNetConn) SetWriteDeadline(time.Time) error { return nil }

type fakeHalfCloseConn struct {
	fakeNetConn
	closeReadCount  atomic.Int32
	closeWriteCount atomic.Int32
}

func (c *fakeHalfCloseConn) CloseRead() error {
	c.closeReadCount.Add(1)
	return nil
}

func (c *fakeHalfCloseConn) CloseWrite() error {
	c.closeWriteCount.Add(1)
	return nil
}

type halfCloseTestConn interface {
	net.Conn
	CloseRead() error
	CloseWrite() error
}

func waitForCondition(t *testing.T, timeout time.Duration, ok func() bool) {
	t.Helper()
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		if ok() {
			return
		}
		time.Sleep(10 * time.Millisecond)
	}
	t.Fatal("condition was not met before timeout")
}

// All values in this file are local fixtures; the control plane transport
// rejects every request it does not recognise.

func coreFixtureJWT(lifetime time.Duration) string {
	now := time.Now()
	claims := fmt.Sprintf(`{"sub":"fixture","aud":"https://vpn.mozilla.org","iss":"https://vpn.mozilla.org","iat":%d,"nbf":%d,"exp":%d}`, now.Unix(), now.Unix(), now.Add(lifetime).Unix())
	return "e30." + base64.RawURLEncoding.EncodeToString([]byte(claims)) + ".local-only"
}

func coreResponse(r *http.Request, status int, body string, header http.Header) *http.Response {
	if header == nil {
		header = make(http.Header)
	}
	return &http.Response{StatusCode: status, Header: header, Body: io.NopCloser(strings.NewReader(body)), Request: r}
}

func setCoreControlPlane(t *testing.T, handler func(*http.Request) (*http.Response, error)) {
	t.Helper()
	t.Setenv("USERPROFILE", t.TempDir())
	t.Setenv("HOME", t.TempDir())
	controlplane.SetTransport(auditRoundTripper(handler))
	t.Cleanup(func() { controlplane.SetTransport(nil) })
	previousDelay := GuardianRetryInitialDelay
	GuardianRetryInitialDelay = time.Millisecond
	t.Cleanup(func() { GuardianRetryInitialDelay = previousDelay })
}

func liveShapedCountries() []serverlist.Country {
	server := func(host string) []serverlist.City {
		return []serverlist.City{{Name: host, Code: host, Servers: []serverlist.Server{{Hostname: host, Port: 2499}}}}
	}
	return []serverlist.Country{
		{Name: "United States", Code: "US", Cities: server("us.example")},
		{Name: "United Kingdom", Code: "GB", Locked: true, Cities: server("gb.example")},
		{Name: "Recommended", Code: serverlist.RecommendedCountryCode, Cities: server("anycast.example")},
	}
}
