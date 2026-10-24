package main

import (
	"context"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/tls"
	"crypto/x509"
	"fmt"
	"io"
	"math/big"
	"net"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

// Reproduce a usable relay whose account metadata and first probe host fail.
// All traffic stays on the local HTTP/2 fixture, with certificate verification.
func TestRelayStartsWhenMetadataAndOneProbeAreUnavailable(t *testing.T) {
	key, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	cert := &x509.Certificate{SerialNumber: big.NewInt(499), DNSNames: []string{"detectportal.firefox.com", "cp.cloudflare.com"},
		NotBefore: time.Now().Add(-time.Minute), NotAfter: time.Now().Add(time.Hour), KeyUsage: x509.KeyUsageDigitalSignature, ExtKeyUsage: []x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth}}
	der, err := x509.CreateCertificate(rand.Reader, cert, cert, &key.PublicKey, key)
	if err != nil {
		t.Fatal(err)
	}
	var first, fallback, metadata atomic.Int32
	target := httptest.NewUnstartedServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if strings.HasPrefix(r.Host, "detectportal") {
			first.Add(1)
			w.WriteHeader(403)
			return
		}
		fallback.Add(1)
		w.WriteHeader(204)
	}))
	target.TLS = &tls.Config{Certificates: []tls.Certificate{{Certificate: [][]byte{der}, PrivateKey: key}}}
	target.StartTLS()
	defer target.Close()
	edge := httptest.NewUnstartedServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != "CONNECT" || r.ProtoMajor != 2 || r.Header.Get("Proxy-Authorization") != "Bearer valid-pass" {
			w.WriteHeader(407)
			return
		}
		conn, e := net.Dial("tcp", target.Listener.Addr().String())
		if e != nil {
			w.WriteHeader(502)
			return
		}
		defer conn.Close()
		w.WriteHeader(200)
		w.(http.Flusher).Flush()
		go func() { io.Copy(conn, r.Body); conn.Close() }()
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
	}))
	edge.EnableHTTP2 = true
	edge.StartTLS()
	defer edge.Close()
	host, port, _ := net.SplitHostPort(edge.Listener.Addr().String())
	catalog := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if strings.Contains(r.URL.Path, "/status") {
			metadata.Add(1)
			w.WriteHeader(503)
			return
		}
		fmt.Fprintf(w, `{"data":[{"code":"DE","cities":[{"servers":[{"hostname":%q,"port":%s}]}]}]}`, host, port)
	}))
	defer catalog.Close()
	p := newProvider(State{AccessToken: "access", ExpiresAt: time.Now().Unix() + 3600})
	p.pass = "valid-pass"
	p.passExpiry = time.Now().Unix() + 3600
	p.settingsURL = catalog.URL
	p.guardianURL = catalog.URL
	p.roots = x509.NewCertPool()
	p.roots.AddCert(edge.Certificate())
	leaf, _ := x509.ParseCertificate(der)
	p.roots.AddCert(leaf)
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	address, err := p.prepareRelay(ctx, "DE", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer p.listener.Close()
	defer p.closeRelays()
	if address == "" || metadata.Load() != 0 || first.Load() != 1 || fallback.Load() != 1 {
		t.Fatal(address, metadata.Load(), first.Load(), fallback.Load())
	}
}
