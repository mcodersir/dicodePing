package controlplane

import (
	"context"
	"crypto/x509"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

func TestDirectHTTP2NegotiatesH2WithPlatformRoots(t *testing.T) {
	server := httptest.NewUnstartedServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.ProtoMajor != 2 {
			t.Error("HTTP/2 was not negotiated")
		}
		w.Write([]byte("h2-fixture"))
	}))
	server.EnableHTTP2 = true
	server.StartTLS()
	defer server.Close()
	roots := x509.NewCertPool()
	roots.AddCert(server.Certificate())
	SetRoots(roots)
	t.Cleanup(func() { SetRoots(nil) })
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	req, _ := http.NewRequestWithContext(ctx, http.MethodGet, server.URL, nil)
	ApplyFirefoxHeaders(req)
	resp, err := DoDirectHTTP2(req)
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(resp.Body)
	if err != nil || resp.ProtoMajor != 2 || string(body) != "h2-fixture" {
		t.Fatalf("direct HTTP/2 failed: %v", err)
	}
}

func TestControlPlaneReplays406OverPlatformTLSHTTP2(t *testing.T) {
	var h1, h2 atomic.Int32
	server := httptest.NewUnstartedServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		if r.Method != http.MethodPost || r.URL.Path != "/token" || string(body) != "same-grant" || r.Header.Get("Authorization") != "Bearer fixture" || r.Header.Get("Accept-Encoding") != "identity" {
			t.Error("recovery changed the control-plane request")
			w.WriteHeader(500)
			return
		}
		if r.ProtoMajor == 1 {
			h1.Add(1)
			w.WriteHeader(http.StatusNotAcceptable)
			return
		}
		h2.Add(1)
		w.Write([]byte("recovered"))
	}))
	server.EnableHTTP2 = true
	server.StartTLS()
	defer server.Close()
	roots := x509.NewCertPool()
	roots.AddCert(server.Certificate())
	SetRoots(roots)
	t.Cleanup(func() { SetRoots(nil) })
	req, _ := http.NewRequest(http.MethodPost, server.URL+"/token", strings.NewReader("same-grant"))
	req.Header.Set("Authorization", "Bearer fixture")
	ApplyFirefoxHeaders(req)
	resp, err := Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(resp.Body)
	if resp.StatusCode != 200 || resp.ProtoMajor != 2 || string(body) != "recovered" || h1.Load() != 1 || h2.Load() != 1 {
		t.Fatalf("control-plane recovery failed: status=%d protocol=%s h1=%d h2=%d", resp.StatusCode, resp.Proto, h1.Load(), h2.Load())
	}
}
