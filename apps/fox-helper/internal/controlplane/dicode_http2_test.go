package controlplane

import (
	"context"
	"crypto/x509"
	"io"
	"net/http"
	"net/http/httptest"
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
