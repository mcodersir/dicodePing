package proxy

import (
	"crypto/tls"
	"errors"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"sync/atomic"
	"testing"
	"time"

	"golang.org/x/net/http2"
)

type flushWriter struct{ http.ResponseWriter }

func (w flushWriter) Write(p []byte) (int, error) {
	n, err := w.ResponseWriter.Write(p)
	w.ResponseWriter.(http.Flusher).Flush()
	return n, err
}

// pipeH2Session builds an h2ProxySession as dialH2ProxySession does, over
// an in-process pipe to a CONNECT echo server that allows maxStreams
// streams at a time.
func pipeH2Session(t *testing.T, timeout time.Duration, maxStreams uint32) *h2ProxySession {
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
		(&http2.Server{MaxConcurrentStreams: maxStreams}).ServeConn(serverTLS, &http2.ServeConnOpts{Handler: echo})
	}()
	raw := tls.Client(clientPipe, clientCfg)
	if err := raw.Handshake(); err != nil {
		t.Fatal(err)
	}
	cc, err := (&http2.Transport{StrictMaxConcurrentStreams: true}).NewClientConn(raw)
	if err != nil {
		t.Fatal(err)
	}
	s := &h2ProxySession{raw: raw, cc: cc, proxyHost: "127.0.0.1:443", token: "pass", timeout: timeout, stopKeepAlive: func() {}}
	s.alive.Store(true)
	t.Cleanup(func() { _ = s.Close() })
	return s
}

// A session whose streams are all in use is busy, not dead: it stays
// alive, a waiting tunnel takes the stream that frees up, and tunnels that
// find none in time neither mark the session unhealthy nor rebuild it (a
// rebuild would fetch a new pass for nothing).
func TestSaturatedSessionIsBusyNotDead(t *testing.T) {
	s := pipeH2Session(t, 500*time.Millisecond, 2)
	a, err := s.OpenTunnel("a.example:443")
	if err != nil {
		t.Fatal(err)
	}
	b, err := s.OpenTunnel("b.example:443")
	if err != nil {
		t.Fatal(err)
	}
	defer b.Close()
	if !s.IsAlive() {
		t.Fatal("a saturated session must stay alive")
	}

	waited := make(chan error, 1)
	go func() {
		c, err := s.OpenTunnel("c.example:443")
		if err == nil {
			_ = c.Close()
		}
		waited <- err
	}()
	time.Sleep(100 * time.Millisecond)
	_ = a.Close()
	if err := <-waited; err != nil {
		t.Fatalf("a waiting tunnel must take the freed stream: %v", err)
	}

	a, err = s.OpenTunnel("a.example:443")
	if err != nil {
		t.Fatal(err)
	}
	defer a.Close()
	time.Sleep(50 * time.Millisecond)
	for _, target := range []string{"d.example:443", "e.example:443", "f.example:443", "g.example:443"} {
		_, err := s.OpenTunnel(target)
		if !errors.Is(err, errSessionSaturated) {
			t.Fatalf("%s: want errSessionSaturated, got %v", target, err)
		}
		if errors.Is(err, errProxySessionUnhealthy) || shouldRebuildProxySession(err) {
			t.Fatalf("%s: saturation must not count as a broken session: %v", target, err)
		}
	}
	if !s.IsAlive() {
		t.Fatal("the session must still be alive after saturated opens")
	}
}

// Through the controller, saturation never rebuilds the session.
func TestControllerDoesNotRebuildSaturatedSession(t *testing.T) {
	s := pipeH2Session(t, 300*time.Millisecond, 1)
	var rebuilds atomic.Int32
	c := &Controller{current: &managedSession{session: s, expiresAt: time.Now().Add(10 * time.Minute), accepting: true}}
	c.refreshSession = func() error {
		rebuilds.Add(1)
		return errors.New("a new pass")
	}
	held, err := c.OpenTunnel("a.example:443")
	if err != nil {
		t.Fatal(err)
	}
	defer held.Close()
	time.Sleep(50 * time.Millisecond)
	if _, err := c.OpenTunnel("b.example:443"); !errors.Is(err, errSessionSaturated) {
		t.Fatalf("want errSessionSaturated, got %v", err)
	}
	if n := rebuilds.Load(); n != 0 {
		t.Fatalf("saturation rebuilt the session %d times", n)
	}
}
