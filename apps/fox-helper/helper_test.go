package main

import (
	"context"
	"crypto/sha256"
	"crypto/tls"
	"crypto/x509"
	"encoding/hex"
	"encoding/json"
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

func TestProofOfWorkAndInteractiveChallenges(t *testing.T) {
	sum := sha256.Sum256([]byte("challengea9"))
	v, ok := pow("challenge", hex.EncodeToString(sum[:]))
	if !ok || v != "a9" {
		t.Fatal(v, ok)
	}
	if _, ok := pow("x", "invalid"); ok {
		t.Fatal("invalid proof accepted")
	}
}
func TestAuthPasswordAndHawkAreStable(t *testing.T) {
	v, e := derivePassword("owner@example.com", "password123")
	if e != nil || v != "c703fa3d364473673bd9676b7cf68efc410778b81a85714ef27ebf267d28b6e0" {
		t.Fatalf("derive %s %v", v, e)
	}
	header, e := hawk("POST", "https://api.accounts.firefox.com/v1/oauth/token", strings.Repeat("01", 32), []byte(`{"x":1}`), 1700000000, "nonce")
	if e != nil || !strings.HasPrefix(header, "Hawk id=") || strings.Contains(header, "password123") {
		t.Fatal(header, e)
	}
}
func TestAccountLoginRequiresVerificationAndRefreshKeepsSession(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var body map[string]any
		json.NewDecoder(r.Body).Decode(&body)
		w.Header().Set("Content-Type", "application/json")
		switch r.URL.Path {
		case "/account/login":
			if body["password"] != nil || body["authPW"] == nil {
				t.Error("raw password transmitted")
			}
			io.WriteString(w, `{"verified":false,"sessionToken":"`+strings.Repeat("01", 32)+`","verificationMethod":"email-2fa"}`)
		case "/session/verify_code":
			if body["code"] != "123456" || !strings.HasPrefix(r.Header.Get("Authorization"), "Hawk ") {
				t.Error("verification not authenticated")
			}
			io.WriteString(w, `{}`)
		case "/oauth/token":
			io.WriteString(w, `{"access_token":"access","refresh_token":"refresh","expires_in":3600}`)
		default:
			w.WriteHeader(404)
		}
	}))
	defer server.Close()
	p := newProvider(State{})
	p.authURL = server.URL
	if e := p.login(context.Background(), "owner@example.com", "password123"); e != nil {
		t.Fatal(e)
	}
	if p.state.SessionToken == "" || p.state.AccessToken != "" {
		t.Fatal("verification bypassed")
	}
	if e := p.verify(context.Background(), "123456"); e != nil {
		t.Fatal(e)
	}
	if p.state.SessionToken != "" || p.state.RefreshToken != "refresh" {
		t.Fatal("bad session")
	}
	p.state.ExpiresAt = 0
	if e := p.ensureAuth(context.Background()); e != nil {
		t.Fatal(e)
	}
}
func TestQuotaFailureNeverReturnsProxyPass(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("X-Quota-Remaining", "0")
		io.WriteString(w, `{"token":"secret-proxy-pass"}`)
	}))
	defer server.Close()
	p := newProvider(State{AccessToken: "token", ExpiresAt: time.Now().Unix() + 3600})
	p.guardianURL = server.URL
	for attempt := 0; attempt < 2; attempt++ {
		if _, e := p.proxyPassLocked(context.Background()); e == nil {
			t.Fatal("zero quota accepted, including cached pass")
		}
	}
}
func TestSOCKSUsesRealHTTP2ConnectAndClosesOnCancellation(t *testing.T) {
	var requests, connects atomic.Int32
	target := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		requests.Add(1)
		io.WriteString(w, "real HTTP2 proxy data")
	}))
	defer target.Close()
	proxy := httptest.NewUnstartedServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != "CONNECT" || r.ProtoMajor != 2 || r.Header.Get("Proxy-Authorization") != "Bearer test-pass" {
			t.Error("bad proxy handshake")
			w.WriteHeader(407)
			return
		}
		connects.Add(1)
		conn, e := net.Dial("tcp", r.Host)
		if e != nil {
			w.WriteHeader(502)
			return
		}
		defer conn.Close()
		w.WriteHeader(200)
		w.(http.Flusher).Flush()
		done := make(chan struct{})
		go func() {
			io.Copy(conn, r.Body)
			if tcp, ok := conn.(*net.TCPConn); ok {
				tcp.CloseWrite()
			}
			close(done)
		}()
		buf := make([]byte, 8192)
		for {
			n, e := conn.Read(buf)
			if n > 0 {
				w.Write(buf[:n])
				w.(http.Flusher).Flush()
			}
			if e != nil {
				break
			}
		}
		r.Body.Close()
		<-done
	}))
	proxy.EnableHTTP2 = true
	proxy.StartTLS()
	defer proxy.Close()
	roots := x509.NewCertPool()
	roots.AddCert(proxy.Certificate())
	u, _ := url.Parse(proxy.URL)
	host, port, _ := net.SplitHostPort(u.Host)
	p := newProvider(State{})
	p.pass = "test-pass"
	p.passExpiry = time.Now().Unix() + 3600
	p.selected = Location{Host: host, Port: mustPort(port)}
	p.streams = &http.Transport{ForceAttemptHTTP2: true, TLSClientConfig: &tls.Config{RootCAs: roots, MinVersion: tls.VersionTLS12}}
	listener, e := net.Listen("tcp", "127.0.0.1:0")
	if e != nil {
		t.Fatal(e)
	}
	p.listener = listener
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() { done <- p.serve(ctx) }()
	proxyURL, _ := url.Parse("socks5://" + listener.Addr().String())
	client := &http.Client{Timeout: 8 * time.Second, Transport: &http.Transport{Proxy: http.ProxyURL(proxyURL)}}
	resp, e := client.Get(target.URL)
	if e != nil {
		cancel()
		t.Fatal(e)
	}
	body, _ := io.ReadAll(resp.Body)
	resp.Body.Close()
	client.CloseIdleConnections()
	if string(body) != "real HTTP2 proxy data" || requests.Load() != 1 || connects.Load() != 1 {
		t.Fatal("request bypassed proxy", string(body), requests.Load(), connects.Load())
	}
	// Startup / encrypted DNS uses HTTP Transport's cancellable dial context.
	viaTunnel := p.dohClient()
	for i := 0; i < 2; i++ {
		response, err := viaTunnel.Get(target.URL)
		if err != nil {
			cancel()
			t.Fatalf("HTTP-over-CONNECT failed: %v", err)
		}
		payload, err := io.ReadAll(response.Body)
		response.Body.Close()
		if err != nil || string(payload) != "real HTTP2 proxy data" {
			cancel()
			t.Fatal(string(payload), err)
		}
	}
	viaTunnel.CloseIdleConnections()
	if requests.Load() != 3 {
		cancel()
		t.Fatal("missing proxied requests", requests.Load())
	}
	cancel()
	select {
	case <-done:
	case <-time.After(3 * time.Second):
		t.Fatal("listener did not stop")
	}
	if c, e := net.DialTimeout("tcp", listener.Addr().String(), time.Second); e == nil {
		c.Close()
		t.Fatal("listener survived stop")
	}
}
func mustPort(s string) int {
	n := 0
	for _, c := range s {
		n = n*10 + int(c-'0')
	}
	return n
}

func TestPublicServerListUsesCompatibleLocationsAndSkipsQuarantine(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		io.WriteString(w, `{"data":[{"code":"DE","name":"Germany","cities":[{"code":"FRA","name":"Frankfurt","servers":[{"hostname":"first.example","port":2499},{"hostname":"quarantined.example","port":2499,"quarantined":true},{"hostname":"second.example","port":1,"protocols":[{"name":"connect","host":"h2.example","port":443}]}]}]}]}`)
	}))
	defer server.Close()
	p := newProvider(State{})
	p.settingsURL = server.URL
	locations, e := p.locations(context.Background())
	if e != nil || len(locations) != 2 || locations[1].Host != "h2.example" || locations[1].Port != 443 {
		t.Fatal(locations, e)
	}
}

func TestGuardianActivatesOnTokenRejectionBeforeRetry(t *testing.T) {
	var calls []string
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls = append(calls, r.Method+" "+r.URL.Path)
		if r.Header.Get("Authorization") != "Bearer access" {
			t.Error("missing account authorization")
		}
		switch r.URL.Path {
		case "/api/v1/fpn/token":
			if len(calls) == 1 {
				w.WriteHeader(403)
				io.WriteString(w, `{}`)
				return
			}
			w.Header().Set("X-Quota-Limit", "53687091200")
			w.Header().Set("X-Quota-Remaining", "50000000000")
			io.WriteString(w, `{"token":"valid-pass"}`)
		case "/api/v1/fpn/activate":
			io.WriteString(w, `{}`)
		case "/api/v1/fpn/status":
			io.WriteString(w, `{"uid":"123","limited_bandwidth":true}`)
		}
	}))
	defer server.Close()
	p := newProvider(State{AccessToken: "access", ExpiresAt: time.Now().Unix() + 3600})
	p.guardianURL = server.URL
	info, err := p.account(context.Background())
	if err != nil || info.UID != "123" || info.QuotaMax == nil || *info.QuotaMax != 53687091200 {
		t.Fatal(info, err)
	}
	expected := "GET /api/v1/fpn/token,POST /api/v1/fpn/activate,GET /api/v1/fpn/token,GET /api/v1/fpn/status"
	if strings.Join(calls, ",") != expected {
		t.Fatal(calls)
	}
}

func TestValidPassDoesNotRequireStatusPermissionOrActivation(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/api/v1/fpn/token":
			w.Header().Set("X-Quota-Remaining", "42")
			io.WriteString(w, `{"token":"valid-pass"}`)
		case "/api/v1/fpn/status":
			w.WriteHeader(403)
		case "/api/v1/fpn/activate":
			t.Error("unnecessary activation")
			w.WriteHeader(500)
		}
	}))
	defer server.Close()
	p := newProvider(State{AccessToken: "access", ExpiresAt: time.Now().Unix() + 3600})
	p.guardianURL = server.URL
	info, err := p.account(context.Background())
	if err != nil || info.QuotaRemaining == nil || *info.QuotaRemaining != 42 {
		t.Fatal(info, err)
	}
}

func TestActivationRejectionIsBoundedAndKeepsSession(t *testing.T) {
	calls := 0
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { calls++; w.WriteHeader(403) }))
	defer server.Close()
	p := newProvider(State{AccessToken: "access", RefreshToken: "refresh", ExpiresAt: time.Now().Unix() + 3600})
	p.guardianURL = server.URL
	_, err := p.account(context.Background())
	api, ok := err.(*ProviderError)
	if !ok || api.Code != "activation_required" || calls != 2 || p.state.RefreshToken != "refresh" {
		t.Fatal(err, calls)
	}
}
