package main

import (
	"context"
	"crypto/tls"
	"crypto/x509"
	"net"
	"net/http"
	"net/http/httptest"
	"sync/atomic"
	"testing"
	"time"
)

func TestRejectedProxyPassRenewsOnceWithoutRestartingSession(t *testing.T) {
	for _, rejectsFresh := range []bool{false, true} {
		t.Run(map[bool]string{false: "renewed", true: "bounded-rejection"}[rejectsFresh], func(t *testing.T) {
			var tokens, connects atomic.Int32
			guardian := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				if r.URL.Path != "/api/v1/fpn/token" {
					t.Error("unexpected provider operation", r.URL.Path)
				}
				tokens.Add(1)
				w.Write([]byte(`{"token":"fresh","expires_at":9999999999}`))
			}))
			defer guardian.Close()
			edge := httptest.NewUnstartedServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				connects.Add(1)
				if r.Header.Get("Proxy-Authorization") != "Bearer fresh" || rejectsFresh {
					w.WriteHeader(407)
					return
				}
				w.WriteHeader(200)
				w.(http.Flusher).Flush()
				<-r.Context().Done()
			}))
			edge.EnableHTTP2 = true
			edge.StartTLS()
			defer edge.Close()
			host, port, _ := net.SplitHostPort(edge.Listener.Addr().String())
			roots := x509.NewCertPool()
			roots.AddCert(edge.Certificate())
			p := newProvider(State{AccessToken: "access", ExpiresAt: time.Now().Unix() + 3600})
			p.guardianURL = guardian.URL
			p.pass = "expired-pass"
			p.passExpiry = time.Now().Unix() + 3600
			p.selected = Location{Host: host, Port: mustPort(port)}
			p.streams = &http.Transport{ForceAttemptHTTP2: true, TLSClientConfig: &tls.Config{RootCAs: roots}}
			defer p.streams.CloseIdleConnections()
			ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
			defer cancel()
			conn, err := p.openTunnel(ctx, "destination.invalid:443")
			if conn != nil {
				conn.Close()
			}
			if (err != nil) != rejectsFresh {
				t.Fatal("unexpected pass renewal outcome", err)
			}
			if tokens.Load() != 1 || connects.Load() != 2 {
				t.Fatalf("unbounded renewal: tokens=%d connects=%d", tokens.Load(), connects.Load())
			}
		})
	}
}
