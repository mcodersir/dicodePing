//go:build with_utls

package main

import (
	"context"
	"encoding/pem"
	"errors"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"sync/atomic"
	"testing"
	"time"
)

func TestSingRelayPreservesBoundedAuthAndRateLimitErrors(t *testing.T) {
	for _, status := range []int{401, 407, 429} {
		t.Run(http.StatusText(status), func(t *testing.T) {
			var tokens, connects atomic.Int32
			guardian := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				tokens.Add(1)
				_, _ = w.Write([]byte(`{"token":"fresh","expires_at":9999999999}`))
			}))
			defer guardian.Close()
			edge := httptest.NewUnstartedServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { connects.Add(1); w.WriteHeader(status) }))
			edge.EnableHTTP2 = true
			edge.StartTLS()
			defer edge.Close()
			host, port, _ := net.SplitHostPort(edge.Listener.Addr().String())
			p := newProvider(State{AccessToken: "access", ExpiresAt: time.Now().Unix() + 3600})
			p.guardianURL = guardian.URL
			p.useSingBox = true
			p.pass, p.passExpiry = "initial", time.Now().Unix()+3600
			p.selected = Location{Host: host, Port: mustPort(port)}
			if err := p.installRoots(string(pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: edge.Certificate().Raw}))); err != nil {
				t.Fatal(err)
			}
			p.tlsSplit = "off"
			var err error
			p.engine, err = p.newSingRelay()
			if err != nil {
				t.Fatal(err)
			}
			defer p.closeRelays()
			ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
			defer cancel()
			_, err = p.openTunnel(ctx, "destination.invalid:443")
			var providerError *ProviderError
			if !errors.As(err, &providerError) {
				t.Fatal("provider error became an unclassified network failure", err)
			}
			if status == 429 {
				if providerError.Code != "rate_limited" || connects.Load() != 1 || tokens.Load() != 0 {
					t.Fatal("rate limiting caused renewal or incorrect quota exhaustion", providerError, connects.Load(), tokens.Load())
				}
			} else if providerError.Code != "login_required" || connects.Load() != 2 || tokens.Load() != 1 {
				t.Fatal("rejected credentials were not renewed exactly once", providerError, connects.Load(), tokens.Load())
			}
		})
	}
}

func TestSingRelayRotatesBearerWithoutDroppingActiveStream(t *testing.T) {
	var refreshes atomic.Int32
	guardian := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		refreshes.Add(1)
		_, _ = w.Write([]byte(`{"token":"fresh","expires_at":9999999999}`))
	}))
	defer guardian.Close()
	var reject atomic.Bool
	edge := httptest.NewUnstartedServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.ProtoMajor != 2 || r.Method != "CONNECT" {
			t.Error("expected HTTP/2 CONNECT")
		}
		want := "Bearer initial"
		if reject.Load() {
			want = "Bearer fresh"
		}
		if r.Header.Get("Proxy-Authorization") != want {
			w.WriteHeader(407)
			return
		}
		w.WriteHeader(200)
		w.(http.Flusher).Flush()
		buffer := make([]byte, 1024)
		for {
			n, err := r.Body.Read(buffer)
			if n > 0 {
				_, _ = w.Write(buffer[:n])
				w.(http.Flusher).Flush()
			}
			if err != nil {
				return
			}
		}
	}))
	edge.EnableHTTP2 = true
	edge.StartTLS()
	defer edge.Close()
	p := newProvider(State{AccessToken: "access", ExpiresAt: time.Now().Unix() + 3600})
	p.useSingBox = true
	p.guardianURL = guardian.URL
	p.pass, p.passExpiry = "initial", time.Now().Unix()+3600
	host, port, _ := net.SplitHostPort(edge.Listener.Addr().String())
	p.selected = Location{Host: host, Port: mustPort(port)}
	if err := p.installRoots(string(pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: edge.Certificate().Raw}))); err != nil {
		t.Fatal(err)
	}
	p.tlsSplit = "off"
	var err error
	p.engine, err = p.newSingRelay()
	if err != nil {
		t.Fatal(err)
	}
	defer p.closeRelays()
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	first, err := p.openTunnel(ctx, "destination.invalid:443")
	if err != nil {
		t.Fatal(err)
	}
	defer first.Close()
	echo := func(conn net.Conn) {
		t.Helper()
		_ = conn.SetDeadline(time.Now().Add(3 * time.Second))
		if _, err := conn.Write([]byte("hello")); err != nil {
			t.Fatal(err)
		}
		data := make([]byte, 5)
		if _, err := io.ReadFull(conn, data); err != nil {
			t.Fatal(err)
		}
		if string(data) != "hello" {
			t.Fatal("relay corrupted payload")
		}
	}
	echo(first)
	reject.Store(true)
	second, err := p.openTunnel(ctx, "destination.invalid:443")
	if err != nil {
		t.Fatal(err)
	}
	defer second.Close()
	echo(second)
	echo(first)
	if refreshes.Load() != 1 {
		t.Fatal("expected one bounded credential refresh", refreshes.Load())
	}
}

func TestSingRelayRejectsUntrustedCertificate(t *testing.T) {
	edge := httptest.NewUnstartedServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { t.Error("untrusted server received request") }))
	edge.EnableHTTP2 = true
	edge.StartTLS()
	defer edge.Close()
	host, port, _ := net.SplitHostPort(edge.Listener.Addr().String())
	p := newProvider(State{})
	p.pass, p.passExpiry = "initial", time.Now().Unix()+3600
	p.selected = Location{Host: host, Port: mustPort(port)}
	p.useSingBox = true
	p.tlsSplit = "off"
	var err error
	p.engine, err = p.newSingRelay()
	if err != nil {
		t.Fatal(err)
	}
	defer p.closeRelays()
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if conn, err := p.openTunnel(ctx, "destination.invalid:443"); err == nil {
		conn.Close()
		t.Fatal("untrusted TLS accepted")
	}
}
