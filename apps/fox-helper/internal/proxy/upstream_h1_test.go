package proxy

import (
	"bufio"
	"crypto/tls"
	"crypto/x509"
	"errors"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

// h1Server is a Mozilla-like proxy speaking HTTP/1.1 CONNECT over TLS on
// loopback: the pass "good" opens a tunnel that echoes, any other gets the
// answer Mozilla gives, 400 Bad Request (JWT). It counts its connections.
func h1Server(t *testing.T, protos []string) (*url.URL, *atomic.Int32) {
	t.Helper()
	fixture := httptest.NewUnstartedServer(nil)
	fixture.StartTLS()
	t.Cleanup(fixture.Close)
	pool := x509.NewCertPool()
	pool.AddCert(fixture.Certificate())
	previous := upstreamRoots.Load()
	upstreamRoots.Store(pool)
	t.Cleanup(func() { upstreamRoots.Store(previous); upstreamGoTLS.Store(false) })
	config := fixture.TLS.Clone()
	config.NextProtos = protos
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = listener.Close() })
	var count atomic.Int32
	go func() {
		for {
			conn, err := listener.Accept()
			if err != nil {
				return
			}
			count.Add(1)
			go func() {
				defer conn.Close()
				server := tls.Server(conn, config)
				if server.Handshake() != nil {
					return
				}
				br := bufio.NewReader(server)
				req, err := http.ReadRequest(br)
				if err != nil {
					return
				}
				if req.Method != http.MethodConnect || req.Header.Get("Proxy-Authorization") != "Bearer good" ||
					!strings.Contains(req.Header.Get("User-Agent"), "Firefox") {
					io.WriteString(server, "HTTP/1.1 400 Bad Request (JWT)\r\nContent-Length: 0\r\nX-Fastly-Proxy-Auth-Failed: 1\r\n\r\n")
					return
				}
				io.WriteString(server, "HTTP/1.1 200 Connection Established\r\n\r\n")
				io.Copy(server, br)
			}()
		}
	}()
	return &url.URL{Scheme: "https", Host: listener.Addr().String()}, &count
}

func TestH1SessionTunnels(t *testing.T) {
	target, count := h1Server(t, []string{"http/1.1"})
	s, err := newH1ProxySession(target, "good", 5*time.Second)
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()

	echo := func(conn net.Conn) {
		t.Helper()
		conn.SetDeadline(time.Now().Add(5 * time.Second))
		if _, err := io.WriteString(conn, "hello"); err != nil {
			t.Fatal(err)
		}
		buf := make([]byte, 5)
		if _, err := io.ReadFull(conn, buf); err != nil || string(buf) != "hello" {
			t.Fatalf("echo = %q, %v", buf, err)
		}
	}
	first, err := s.OpenTunnel("example.com:443")
	if err != nil {
		t.Fatal(err)
	}
	echo(first)
	second, err := s.OpenTunnel("example.org:443")
	if err != nil {
		t.Fatal(err)
	}
	echo(second)
	echo(first)
	// Each tunnel its own connection: the first spare, then spares made
	// in the background or fresh ones.
	if n := count.Load(); n < 2 {
		t.Fatalf("%d connections for two tunnels", n)
	}

	if err := s.UpdateToken("expired"); err != nil {
		t.Fatal(err)
	}
	_, err = s.OpenTunnel("example.com:443")
	var refused *proxyConnectHTTPError
	if !errors.As(err, &refused) || refused.statusCode != http.StatusBadRequest {
		t.Fatalf("expired pass: %v, want 400", err)
	}

	s.Close()
	if s.IsAlive() {
		t.Fatal("alive after Close")
	}
	first.SetReadDeadline(time.Now().Add(2 * time.Second))
	if _, err := first.Read(make([]byte, 1)); err == nil {
		t.Fatal("a tunnel stayed open after Close")
	}
	if _, err := s.OpenTunnel("example.com:443"); err == nil {
		t.Fatal("a tunnel opened after Close")
	}
}

// The protocol TLS agreed on must be the one asked for; a server naming
// none speaks HTTP/1.1, as plain HTTPS servers do.
func TestNegotiated(t *testing.T) {
	for _, c := range []struct {
		proto, got string
		want       error
	}{
		{alpnH1, "http/1.1", nil},
		{alpnH1, "", nil},
		{alpnH1, "h2", errProxyHTTP1Unavailable},
		{alpnH2, "h2", nil},
		{alpnH2, "", errProxyHTTP2Unavailable},
		{alpnH2, "http/1.1", errProxyHTTP2Unavailable},
	} {
		if err := negotiated(c.proto, c.got); err != c.want {
			t.Errorf("negotiated(%q, %q) = %v, want %v", c.proto, c.got, err, c.want)
		}
	}
}

// A spare the server closed while it waited is replaced by a fresh
// connection, unseen by the tunnel.
func TestH1SessionReplacesAStaleSpare(t *testing.T) {
	target, _ := h1Server(t, []string{"http/1.1"})
	s, err := newH1ProxySession(target, "good", 5*time.Second)
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	s.mu.Lock()
	s.spare.Close()
	s.mu.Unlock()
	conn, err := s.OpenTunnel("example.com:443")
	if err != nil {
		t.Fatalf("after a closed spare: %v", err)
	}
	conn.Close()
}
