package proxy

import (
	"context"
	"crypto/tls"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"sync/atomic"
	"syscall"
	"testing"
	"time"

	"golang.org/x/net/http2"

	"dicodeping/fox/internal/logx"
)

// cuttableConn carries its connection until cut, then carries nothing,
// as a network that stops passing a connection's packets: reads wait and
// writes vanish.
type cuttableConn struct {
	net.Conn
	cut    atomic.Bool
	closed chan struct{}
	once   sync.Once
}

func newCuttableConn(conn net.Conn) *cuttableConn {
	return &cuttableConn{Conn: conn, closed: make(chan struct{})}
}

func (c *cuttableConn) Read(p []byte) (int, error) {
	if c.cut.Load() {
		<-c.closed
		return 0, net.ErrClosed
	}
	n, err := c.Conn.Read(p)
	if c.cut.Load() {
		<-c.closed
		return 0, net.ErrClosed
	}
	return n, err
}

func (c *cuttableConn) Write(p []byte) (int, error) {
	if c.cut.Load() {
		return len(p), nil
	}
	return c.Conn.Write(p)
}

func (c *cuttableConn) Close() error {
	c.once.Do(func() { close(c.closed) })
	return c.Conn.Close()
}

// logLines collects the log while the test runs.
type logLines struct {
	mu  sync.Mutex
	buf strings.Builder
}

func (l *logLines) Write(p []byte) (int, error) {
	l.mu.Lock()
	defer l.mu.Unlock()
	return l.buf.Write(p)
}

func (l *logLines) String() string {
	l.mu.Lock()
	defer l.mu.Unlock()
	return l.buf.String()
}

func captureLog(t *testing.T) *logLines {
	t.Helper()
	forgetConnectionLosses(t)
	lines := &logLines{}
	logx.SetOutput(lines)
	t.Cleanup(func() { logx.SetOutput(io.Discard) })
	return lines
}

// forgetConnectionLosses clears the losses that reportConnectionLost
// remembers, for this test and after it.
func forgetConnectionLosses(t *testing.T) {
	t.Helper()
	clear := func() {
		connLosses.Lock()
		connLosses.lives = nil
		connLosses.Unlock()
	}
	clear()
	t.Cleanup(clear)
}

// watchedH2Session is an h2ProxySession over a pipe to an HTTP/2 CONNECT
// echo server, as dialH2ProxySession builds it (a watchedConn under the
// TLS, its keepalive running), with the pipe cuttable.
func watchedH2Session(t *testing.T) (*h2ProxySession, *cuttableConn) {
	t.Helper()
	fixture := httptest.NewUnstartedServer(http.NotFoundHandler())
	fixture.EnableHTTP2 = true
	fixture.StartTLS()
	t.Cleanup(fixture.Close)
	clientCfg := fixture.Client().Transport.(*http.Transport).TLSClientConfig.Clone()
	clientCfg.NextProtos, clientCfg.ServerName = []string{"h2"}, "127.0.0.1"
	serverCfg := fixture.TLS.Clone()
	serverCfg.NextProtos = []string{"h2"}

	clientPipe, serverPipe := net.Pipe()
	t.Cleanup(func() { _ = serverPipe.Close(); _ = clientPipe.Close() })
	echo := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		w.(http.Flusher).Flush()
		_, _ = io.Copy(flushWriter{w}, r.Body)
	})
	go func() {
		serverTLS := tls.Server(serverPipe, serverCfg)
		if serverTLS.Handshake() != nil {
			return
		}
		(&http2.Server{}).ServeConn(serverTLS, &http2.ServeConnOpts{Handler: echo})
	}()
	cuttable := newCuttableConn(clientPipe)
	watched := newWatchedConn(cuttable)
	raw := tls.Client(watched, clientCfg)
	if err := raw.Handshake(); err != nil {
		t.Fatal(err)
	}
	cc, err := (&http2.Transport{StrictMaxConcurrentStreams: true}).NewClientConn(raw)
	if err != nil {
		t.Fatal(err)
	}
	s := &h2ProxySession{raw: raw, cc: cc, watched: watched, opened: time.Now(), proxyHost: "p.example:2499", token: "pass", timeout: 5 * time.Second}
	s.alive.Store(true)
	ctx, cancel := context.WithCancel(context.Background())
	s.stopKeepAlive = cancel
	go s.runKeepAlive(ctx)
	t.Cleanup(func() { _ = s.Close() })
	return s, cuttable
}

func shortKeepAlive(t *testing.T) {
	t.Helper()
	interval, timeout := upstreamKeepAliveInterval, upstreamKeepAlivePingTimeout
	upstreamKeepAliveInterval, upstreamKeepAlivePingTimeout = 50*time.Millisecond, 50*time.Millisecond
	t.Cleanup(func() { upstreamKeepAliveInterval, upstreamKeepAlivePingTimeout = interval, timeout })
}

// A connection the network stops carrying is found by the keepalive
// within a few PINGs and closed, so the tunnels waiting on it fail at once
// (and are retried on a new session) instead of waiting out their CONNECT
// timeout; one log line says what happened.
func TestKeepAliveClosesAConnectionTheNetworkStoppedCarrying(t *testing.T) {
	shortKeepAlive(t)
	lines := captureLog(t)
	s, cuttable := watchedH2Session(t)
	conn, err := s.OpenTunnel("a.example:443")
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close()
	time.Sleep(3 * upstreamKeepAliveInterval)
	if !s.IsAlive() {
		t.Fatal("a connection that answers its PINGs died")
	}

	cuttable.cut.Store(true)
	waiting := make(chan error, 1)
	go func() {
		_, err := s.OpenTunnel("b.example:443")
		waiting <- err
	}()
	select {
	case err := <-waiting:
		if err == nil {
			t.Fatal("a tunnel opened on a cut connection")
		}
	case <-time.After(2 * time.Second):
		t.Fatal("the tunnel still waits on the dead connection")
	}
	if s.IsAlive() || !s.cc.State().Closed {
		t.Fatalf("alive=%v state=%+v; want the dead connection closed", s.IsAlive(), s.cc.State())
	}
	log := lines.String()
	if !strings.Contains(log, "upstream connection lost proxy=p.example:2499") || !strings.Contains(log, `reason="no answer from the network"`) {
		t.Fatalf("log:\n%s", log)
	}
	if strings.Count(log, "upstream connection lost") != 1 {
		t.Fatalf("one loss, one line:\n%s", log)
	}
}

// A PING that waits behind data is no miss: the data shows the connection
// alive.
func TestWatchedConnNotesArrivingData(t *testing.T) {
	a, b := net.Pipe()
	defer a.Close()
	defer b.Close()
	w := newWatchedConn(a)
	before := time.Now()
	go func() { _, _ = b.Write([]byte("x")) }()
	if _, err := w.Read(make([]byte, 1)); err != nil {
		t.Fatal(err)
	}
	if !w.readSince(before) {
		t.Fatal("the data that arrived is not noted")
	}
	if w.readSince(time.Now().Add(time.Second)) {
		t.Fatal("data noted before it came")
	}
	_ = b.Close()
	_, err := w.Read(make([]byte, 1))
	if w.failure() == nil || !errors.Is(w.failure(), err) {
		t.Fatalf("failure %v, want the read's %v", w.failure(), err)
	}
}

func TestLossReason(t *testing.T) {
	for _, c := range []struct {
		err  error
		want string
	}{
		{nil, "no answer from the network"},
		{errors.New("read tcp 192.168.8.158:3687->23.235.42.11:2499: wsarecv: A connection attempt failed because the connected party did not properly respond after a period of time"), "no answer from the network"},
		{&net.OpError{Op: "read", Err: timeoutError{}}, "no answer from the network"},
		{errors.New("write tcp 192.168.8.158:5157->23.235.42.11:2499: wsasend: An existing connection was forcibly closed by the remote host."), "cut off (reset)"},
		{&net.OpError{Op: "read", Err: syscall.ECONNRESET}, "cut off (reset)"},
		{fmt.Errorf("reading: %w", io.EOF), "closed by the other side"},
		{errors.New("something else"), "failed"},
	} {
		if got := lossReason(c.err); got != c.want {
			t.Errorf("lossReason(%v) = %q, want %q", c.err, got, c.want)
		}
	}
}

type timeoutError struct{}

func (timeoutError) Error() string   { return "i/o timeout" }
func (timeoutError) Timeout() bool   { return true }
func (timeoutError) Temporary() bool { return true }

// Losses that keep coming soon after the connection opened read as the
// network cutting it, with how often and how soon.
func TestRepeatedLossesShowTheNetworkCuttingTheConnection(t *testing.T) {
	lines := captureLog(t)
	addr := &net.TCPAddr{IP: net.ParseIP("203.0.113.9"), Port: 2499}
	for i := range connLossPattern {
		reportConnectionLost("p.example:2499", addr, time.Duration(30+10*i)*time.Second, 5, nil, nil)
	}
	log := lines.String()
	if strings.Count(log, "upstream connection lost proxy=") != connLossPattern-1 {
		t.Fatalf("the first losses are plain:\n%s", log)
	}
	want := "upstream connection lost again: the network keeps cutting the connection to this server proxy=p.example:2499 ip=203.0.113.9 after=50s"
	if !strings.Contains(log, want) || !strings.Contains(log, "lost_in_10m=3 average_life=40s") {
		t.Fatalf("log:\n%s", log)
	}
}
