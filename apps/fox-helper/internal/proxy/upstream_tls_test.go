package proxy

import (
	"context"
	"crypto/tls"
	"crypto/x509"
	"encoding/binary"
	"fmt"
	"io"
	"net"
	"net/http/httptest"
	"net/url"
	"os"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	utls "github.com/refraction-networking/utls"

	"dicodeping/fox/internal/hellosplit"
)

// parsedHello is what a ClientHello record says, as hex lists.
type parsedHello struct{ ciphers, extensions, groups, keyShares, sigAlgs, alpn string }

func parseHello(p []byte) parsedHello {
	list := func(b []byte) string {
		var s []string
		for i := 0; i+1 < len(b); i += 2 {
			s = append(s, fmt.Sprintf("%04x", binary.BigEndian.Uint16(b[i:])))
		}
		return strings.Join(s, " ")
	}
	var h parsedHello
	at := 5 + 4 + 2 + 32
	at += 1 + int(p[at])
	n := int(binary.BigEndian.Uint16(p[at:]))
	h.ciphers = list(p[at+2 : at+2+n])
	at += 2 + n
	at += 1 + int(p[at])
	end := at + 2 + int(binary.BigEndian.Uint16(p[at:]))
	at += 2
	var ids []string
	for at+4 <= end {
		id := binary.BigEndian.Uint16(p[at:])
		size := int(binary.BigEndian.Uint16(p[at+2:]))
		body := p[at+4 : at+4+size]
		ids = append(ids, fmt.Sprintf("%04x", id))
		switch id {
		case 0x000a:
			h.groups = list(body[2:])
		case 0x000d:
			h.sigAlgs = list(body[2:])
		case 0x0010:
			var names []string
			for i := 2; i < len(body); i += 1 + int(body[i]) {
				names = append(names, string(body[i+1:i+1+int(body[i])]))
			}
			h.alpn = strings.Join(names, " ")
		case 0x0033:
			var shares []string
			for i := 2; i+4 <= len(body); {
				share := int(binary.BigEndian.Uint16(body[i+2:]))
				shares = append(shares, fmt.Sprintf("%04x:%d", binary.BigEndian.Uint16(body[i:]), share))
				i += 4 + share
			}
			h.keyShares = strings.Join(shares, " ")
		}
		at += 4 + size
	}
	h.extensions = strings.Join(ids, " ")
	return h
}

// The hello carries what Firefox 158 sends, in its order.
func TestFirefoxHelloMatchesFirefox(t *testing.T) {
	client, server := net.Pipe()
	defer client.Close()
	defer server.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	failed := make(chan error, 1)
	go func() {
		_, err := firefoxHandshake(ctx, client, "localhost")
		failed <- err
		_ = client.Close()
	}()
	header := make([]byte, 5)
	if _, err := io.ReadFull(server, header); err != nil {
		t.Fatalf("no hello: %v, handshake: %v", err, <-failed)
	}
	body := make([]byte, binary.BigEndian.Uint16(header[3:]))
	if _, err := io.ReadFull(server, body); err != nil {
		t.Fatal(err)
	}
	// Firefox's hello to this name is this long, its encrypted part included.
	if size := len(header) + len(body); size != 1887 {
		t.Fatalf("hello of %d bytes, want 1887", size)
	}
	got := parseHello(append(header, body...))
	want := parsedHello{
		ciphers:    "1301 1303 1302 c02b c02f cca9 cca8 c02c c030 c013 c014 009c 009d 002f 0035",
		extensions: "0000 0017 ff01 000a 000b 0023 0010 0005 0022 0012 0033 002b 000d 002d 001c 001b fe0d",
		groups:     "11ec 001d 0017 0018 0019",
		keyShares:  "11ec:1216 001d:32 0017:65",
		sigAlgs:    "0403 0503 0603 0804 0805 0806 0401 0501 0601 0203 0201",
		alpn:       "h2 http/1.1",
	}
	if got != want {
		t.Fatalf("hello\n got %+v\nwant %+v", got, want)
	}
}

// upstreamTLSServer serves TLS with h2 on a loopback port and trusts it for the
// test. reject closes the connections it names, before TLS.
func upstreamTLSServer(t *testing.T, reject func(n int32) bool) (*url.URL, string, *atomic.Int32) {
	t.Helper()
	fixture := httptest.NewUnstartedServer(nil)
	fixture.EnableHTTP2 = true
	fixture.StartTLS()
	t.Cleanup(fixture.Close)
	pool := x509.NewCertPool()
	pool.AddCert(fixture.Certificate())
	previous := upstreamRoots.Load()
	upstreamRoots.Store(pool)
	t.Cleanup(func() { upstreamRoots.Store(previous); upstreamGoTLS.Store(false) })
	config := fixture.TLS.Clone()
	config.NextProtos = []string{"h2"}
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
			n := count.Add(1)
			go func() {
				defer conn.Close()
				if reject != nil && reject(n) {
					return
				}
				server := tls.Server(conn, config)
				if server.Handshake() != nil {
					return
				}
				_, _ = io.Copy(io.Discard, server)
			}()
		}
	}()
	return &url.URL{Scheme: "https", Host: "127.0.0.1"}, listener.Addr().String(), &count
}

func dialContext(t *testing.T) context.Context {
	t.Helper()
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	t.Cleanup(cancel)
	return ctx
}

// Firefox's hello completes TLS on each way the hello can be split, more than
// once to a server.
func TestDialUpstreamTLSWithFirefoxHello(t *testing.T) {
	proxyURL, host, _ := upstreamTLSServer(t, nil)
	t.Cleanup(func() { hellosplit.Set(hellosplit.Off) })
	for _, way := range []string{hellosplit.Off, hellosplit.FirstByte, hellosplit.SNI, hellosplit.Record} {
		hellosplit.Set(way)
		if way == hellosplit.SNI || way == hellosplit.Record {
			proxyURL = &url.URL{Scheme: "https", Host: "example.com"}
		}
		for round := 0; round < 2; round++ {
			conn, _, err := dialUpstreamTLS(dialContext(t), proxyURL, host)
			if err != nil {
				t.Fatalf("%s: %v", way, err)
			}
			if _, ok := conn.(*utls.UConn); !ok {
				t.Fatalf("%s: dialed with %T, want Firefox's hello", way, conn)
			}
			_ = conn.Close()
		}
	}
}

// A server that refuses Firefox's hello gets Go's, and later connections skip
// the failure.
func TestDialUpstreamTLSFallsBackToGo(t *testing.T) {
	proxyURL, host, count := upstreamTLSServer(t, func(n int32) bool { return n == 1 })
	conn, _, err := dialUpstreamTLS(dialContext(t), proxyURL, host)
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close()
	if _, ok := conn.(*tls.Conn); !ok {
		t.Fatalf("dialed with %T, want Go's TLS", conn)
	}
	if !upstreamGoTLS.Load() {
		t.Fatal("Go's hello passed where Firefox's failed: it must be remembered")
	}
	next, _, err := dialUpstreamTLS(dialContext(t), proxyURL, host)
	if err != nil {
		t.Fatal(err)
	}
	defer next.Close()
	if _, ok := next.(*tls.Conn); !ok {
		t.Fatalf("second dial with %T, want Go's TLS", next)
	}
	if n := count.Load(); n != 3 {
		t.Fatalf("connections: %d, want 3 (the second dial must not try Firefox's hello)", n)
	}
}

// A failure to connect tries nothing else and remembers nothing.
func TestDialUpstreamTLSConnectFailureStays(t *testing.T) {
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	host := listener.Addr().String()
	_ = listener.Close()
	if _, _, err := dialUpstreamTLS(dialContext(t), &url.URL{Scheme: "https", Host: "127.0.0.1"}, host); err == nil {
		t.Fatal("dial to a closed port succeeded")
	}
	if upstreamGoTLS.Load() {
		t.Fatal("a failure to connect says nothing about the hello")
	}
}

// TestFirefoxHelloLive completes TLS with Mozilla's proxy twice. No pass is sent.
// It hits live infrastructure, so it only runs when UPSTREAM_E2E names a server
// (host:port).
func TestFirefoxHelloLive(t *testing.T) {
	host := os.Getenv("UPSTREAM_E2E")
	if host == "" {
		t.Skip("set UPSTREAM_E2E to a proxy's host:port to run the live handshake")
	}
	name, _, err := net.SplitHostPort(host)
	if err != nil {
		t.Fatal(err)
	}
	proxyURL := &url.URL{Scheme: "https", Host: name}
	for round := 0; round < 2; round++ {
		start := time.Now()
		conn, _, err := dialUpstreamTLS(dialContext(t), proxyURL, host)
		if err != nil {
			t.Fatal(err)
		}
		fingerprint, ok := conn.(*utls.UConn)
		if !ok {
			t.Fatalf("dialed with %T, want Firefox's hello", conn)
		}
		state := fingerprint.ConnectionState()
		t.Logf("round %d: %s, %s, %s, resumed=%v, %s", round, state.NegotiatedProtocol, utls.VersionName(state.Version), utls.CipherSuiteName(state.CipherSuite), state.DidResume, time.Since(start).Round(time.Millisecond))
		// The server's session ticket comes after the handshake.
		_ = conn.SetReadDeadline(time.Now().Add(time.Second))
		_, _ = conn.Read(make([]byte, 1024))
		_ = conn.Close()
	}
}
