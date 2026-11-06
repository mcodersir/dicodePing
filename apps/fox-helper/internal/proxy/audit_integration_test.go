package proxy

import (
	"context"
	"crypto/tls"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os/exec"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"dicodeping/fox/internal/controlplane"
	"dicodeping/fox/internal/fxa"

	"github.com/quic-go/quic-go"
	"github.com/quic-go/quic-go/http3"
	"golang.org/x/net/http2"
	"golang.org/x/net/proxy"
)

// All authentication values in this file are local fixtures. The control
// plane transport rejects every unrecognised request instead of using the
// network. No Mozilla account or service credentials are used.
type auditRoundTripper func(*http.Request) (*http.Response, error)

func (f auditRoundTripper) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }

type auditFlushWriter struct{ http.ResponseWriter }

func (w auditFlushWriter) Write(p []byte) (int, error) {
	n, err := w.ResponseWriter.Write(p)
	w.ResponseWriter.(http.Flusher).Flush()
	return n, err
}

func TestAuditSOCKSConnectAndRenewal(t *testing.T) {
	// Serial: renewal changes the process-wide control plane transport and
	// writes OAuth tokens. Keep those writes inside the test's temporary home.
	t.Setenv("USERPROFILE", t.TempDir())
	t.Setenv("HOME", t.TempDir())
	t.Cleanup(func() { controlplane.SetTransport(nil) })

	for _, protocol := range []string{"h2", "h3"} {
		t.Run(protocol, func(t *testing.T) {
			newPass := auditJWT()
			origin := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				fmt.Fprint(w, "local-origin-through-connect")
			}))
			defer origin.Close()
			originURL, _ := url.Parse(origin.URL)
			var oldRequests, newRequests atomic.Int32
			handler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				if r.Method != http.MethodConnect || r.ProtoMajor != map[string]int{"h2": 2, "h3": 3}[protocol] {
					http.Error(w, "CONNECT protocol mismatch", http.StatusBadRequest)
					return
				}
				switch r.Header.Get("Proxy-Authorization") {
				case "Bearer local-pass-before":
					oldRequests.Add(1)
				case "Bearer " + newPass:
					newRequests.Add(1)
				default:
					http.Error(w, "local fixture auth rejected", http.StatusProxyAuthRequired)
					return
				}
				if r.Host == "audit-echo.invalid:12345" {
					w.WriteHeader(http.StatusOK)
					w.(http.Flusher).Flush()
					_, _ = io.Copy(auditFlushWriter{w}, r.Body)
					return
				}
				if r.Host != "audit-web.invalid:80" {
					http.Error(w, "unexpected local fixture target", http.StatusForbidden)
					return
				}
				conn, err := net.DialTimeout("tcp", originURL.Host, 3*time.Second)
				if err != nil {
					http.Error(w, "local origin unavailable", http.StatusBadGateway)
					return
				}
				defer conn.Close()
				w.WriteHeader(http.StatusOK)
				w.(http.Flusher).Flush()
				go func() { _, _ = io.Copy(conn, r.Body) }()
				_, _ = io.Copy(auditFlushWriter{w}, conn)
			})

			session := auditLocalSession(t, protocol, handler)
			var oauthRequests, guardianRequests atomic.Int32
			var persisted atomic.Pointer[runtimeAuth]
			controlplane.SetTransport(auditRoundTripper(func(r *http.Request) (*http.Response, error) {
				header := make(http.Header)
				var body string
				switch {
				case r.URL.String() == "https://api.accounts.firefox.com/v1/oauth/token" && r.Method == http.MethodPost:
					var payload map[string]string
					if err := json.NewDecoder(r.Body).Decode(&payload); err != nil || payload["grant_type"] != "refresh_token" || payload["refresh_token"] != "local-refresh-fixture" {
						return nil, fmt.Errorf("unexpected local OAuth request")
					}
					oauthRequests.Add(1)
					body = `{"access_token":"local-access-after","expires_in":3600,"scope":"profile","token_type":"bearer"}`
				case r.URL.String() == "https://guardian.invalid/api/v1/fpn/token" && r.Method == http.MethodGet && r.Header.Get("Authorization") == "Bearer local-access-after":
					guardianRequests.Add(1)
					body = `{"token":"` + newPass + `"}`
					header.Set("X-Quota-Limit", "5000")
					header.Set("X-Quota-Remaining", "4000")
				default:
					return nil, fmt.Errorf("unrecognised control plane request blocked by local test")
				}
				return &http.Response{StatusCode: http.StatusOK, Header: header, Body: io.NopCloser(strings.NewReader(body)), Request: r}, nil
			}))
			controller := &Controller{
				guardian: "https://guardian.invalid",
				auth: &runtimeAuth{Token: &fxa.TokenResponse{
					AccessToken: "local-access-expired", RefreshToken: "local-refresh-fixture", ExpiresIn: 1,
				}, ObtainedAt: time.Now().Add(-time.Hour), persist: func(a *runtimeAuth) error {
					persisted.Store(a)
					return nil
				}},
				current: &managedSession{session: session, rawToken: "local-pass-before", expiresAt: time.Now().Add(90 * time.Second), accepting: true},
				done:    make(chan struct{}),
				sessionFactory: func(string) (proxySession, error) {
					return nil, fmt.Errorf("renewal unexpectedly replaced the local session")
				},
			}
			defer controller.Close()
			listener, err := net.Listen("tcp", "127.0.0.1:0")
			if err != nil {
				t.Fatal(err)
			}
			defer listener.Close()
			server := NewSOCKSServer(controller, 3*time.Second, 0, 32)
			go func() {
				for {
					conn, err := listener.Accept()
					if err != nil {
						return
					}
					go server.handleConn(conn)
				}
			}()
			dialer, err := proxy.SOCKS5("tcp", listener.Addr().String(), nil, &net.Dialer{Timeout: 3 * time.Second})
			if err != nil {
				t.Fatal(err)
			}
			persistent, err := dialer.Dial("tcp", "audit-echo.invalid:12345")
			if err != nil {
				t.Fatal(err)
			}
			defer persistent.Close()
			_ = persistent.SetDeadline(time.Now().Add(15 * time.Second))
			auditEcho(t, persistent, "before-renewal")
			auditCurlClients(t, listener.Addr().String())
			go controller.RunRenewalLoop()
			deadline := time.Now().Add(3 * time.Second)
			for {
				controller.mu.Lock()
				renewed := controller.current.rawToken == newPass
				controller.mu.Unlock()
				if renewed {
					break
				}
				if time.Now().After(deadline) {
					t.Fatal("background OAuth + Guardian renewal did not complete")
				}
				time.Sleep(5 * time.Millisecond)
			}
			auditEcho(t, persistent, "after-renewal")
			auditCurlClients(t, listener.Addr().String())
			if controller.current.session != session || oauthRequests.Load() != 1 || guardianRequests.Load() != 1 || oldRequests.Load() != 7 || newRequests.Load() != 6 {
				t.Fatalf("session/renewal/CONNECT counts mismatch: OAuth=%d Guardian=%d old=%d new=%d", oauthRequests.Load(), guardianRequests.Load(), oldRequests.Load(), newRequests.Load())
			}
			saved := persisted.Load()
			if saved == nil || saved.Token.AccessToken != "local-access-after" || saved.Token.RefreshToken != "local-refresh-fixture" {
				t.Fatal("refreshed OAuth credentials were not persisted correctly")
			}
			t.Logf("%s: SOCKS5 %s; 12 curl transfers in two batches of six simultaneous clients; persistent stream survived background OAuth and ProxyPass renewal; upstream session retained", protocol, listener.Addr())
		})
	}
}

func auditJWT() string {
	// Fixed, unsigned, local-only JWT, valid for the duration of this test.
	claims := fmt.Sprintf(`{"iat":%d,"exp":%d}`, time.Now().Truncate(time.Hour).Unix(), time.Now().Truncate(time.Hour).Add(2*time.Hour).Unix())
	return "e30." + base64.RawURLEncoding.EncodeToString([]byte(claims)) + ".local-only"
}

func auditLocalSession(t *testing.T, protocol string, handler http.Handler) proxySession {
	t.Helper()
	// Trust the httptest certificate only for these local sockets. Production
	// TLS verification and the Windows certificate store are unchanged.
	fixture := httptest.NewUnstartedServer(handler)
	fixture.EnableHTTP2 = true
	fixture.StartTLS()
	t.Cleanup(fixture.Close)
	tlsConfig := fixture.Client().Transport.(*http.Transport).TLSClientConfig.Clone()
	tlsConfig.NextProtos = []string{protocol}
	if protocol == "h2" {
		// A local HTTP debugger can replace certificates even on loopback.
		// Keep the upstream TLS byte stream in-process; SOCKS5 clients and
		// the HTTP origin still use real loopback TCP sockets.
		clientPipe, serverPipe := net.Pipe()
		serverTLS := tls.Server(serverPipe, fixture.TLS)
		t.Cleanup(func() { _ = serverPipe.Close() })
		go func() {
			if err := serverTLS.Handshake(); err != nil {
				_ = serverTLS.Close()
				return
			}
			(&http2.Server{}).ServeConn(serverTLS, &http2.ServeConnOpts{Handler: handler})
		}()
		tlsConfig.ServerName = "127.0.0.1"
		raw := tls.Client(clientPipe, tlsConfig)
		_ = raw.SetDeadline(time.Now().Add(3 * time.Second))
		if err := raw.Handshake(); err != nil {
			_ = raw.Close()
			t.Fatal(err)
		}
		_ = raw.SetDeadline(time.Time{})
		cc, err := (&http2.Transport{}).NewClientConn(raw)
		if err != nil {
			raw.Close()
			t.Fatal(err)
		}
		s := &h2ProxySession{raw: raw, cc: cc, proxyHost: fixture.Listener.Addr().String(), token: "local-pass-before", timeout: 3 * time.Second}
		s.alive.Store(true)
		return s
	}
	udp, err := net.ListenPacket("udp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	server := &http3.Server{TLSConfig: fixture.TLS.Clone(), Handler: handler}
	go func() { _ = server.Serve(udp) }()
	t.Cleanup(func() { _ = server.Close(); _ = udp.Close() })
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	conn, err := quic.DialAddr(ctx, udp.LocalAddr().String(), tlsConfig, nil)
	if err != nil {
		t.Fatal(err)
	}
	transport := &http3.Transport{Dial: func(context.Context, string, *tls.Config, *quic.Config) (*quic.Conn, error) { return conn, nil }}
	return &h3ProxySession{conn: conn, rt: transport, proxyHost: udp.LocalAddr().String(), token: "local-pass-before", timeout: 3 * time.Second}
}

func auditEcho(t *testing.T, conn net.Conn, value string) {
	t.Helper()
	if _, err := io.WriteString(conn, value); err != nil {
		t.Fatal(err)
	}
	buf := make([]byte, len(value))
	if _, err := io.ReadFull(conn, buf); err != nil || string(buf) != value {
		t.Fatalf("persistent SOCKS stream failed: %v", err)
	}
}

func auditCurlClients(t *testing.T, addr string) {
	t.Helper()
	curl, err := exec.LookPath("curl.exe")
	if err != nil {
		curl, err = exec.LookPath("curl")
	}
	if err != nil {
		t.Skip("curl is required for the external-client SOCKS5 integration test")
	}
	var wg sync.WaitGroup
	errors := make(chan error, 6)
	for i := 0; i < 6; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
			defer cancel()
			output, err := exec.CommandContext(ctx, curl, "--silent", "--show-error", "--fail", "--max-time", "8", "--noproxy", "", "--socks5-hostname", addr, "--header", "Connection: close", "http://audit-web.invalid/").CombinedOutput()
			if err != nil || string(output) != "local-origin-through-connect" {
				errors <- fmt.Errorf("curl via local CONNECT fixture: %v (%s)", err, output)
			}
		}()
	}
	wg.Wait()
	close(errors)
	for err := range errors {
		t.Error(err)
	}
}
