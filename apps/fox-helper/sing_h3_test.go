//go:build with_utls && with_quic

package main

import (
	"context"
	"crypto/tls"
	"encoding/pem"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/sagernet/quic-go"
	"github.com/sagernet/quic-go/http3"
)

func TestSingHTTP3UsesQUICWithoutTCPFallback(t *testing.T) {
	// UDP and TCP use the same port. Any silent fallback reaches the TCP trap.
	tcp := httptest.NewUnstartedServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { t.Error("HTTP/3 silently fell back to TCP") }))
	tcp.EnableHTTP2 = true
	tcp.StartTLS()
	defer tcp.Close()
	host, port, _ := net.SplitHostPort(tcp.Listener.Addr().String())
	udp, err := net.ListenPacket("udp", tcp.Listener.Addr().String())
	if err != nil {
		t.Fatal(err)
	}
	defer udp.Close()
	listener, err := quic.ListenEarly(udp, &tls.Config{Certificates: tcp.TLS.Certificates, NextProtos: []string{http3.NextProtoH3}}, &quic.Config{EnableDatagrams: true})
	if err != nil {
		t.Fatal(err)
	}
	server := &http3.Server{EnableDatagrams: true, Handler: http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.ProtoMajor != 3 || r.Method != "CONNECT" || r.Header.Get("Proxy-Authorization") != "Bearer h3-pass" {
			t.Error("invalid authenticated HTTP/3 CONNECT")
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
	})}
	go func() { _ = server.ServeListener(listener) }()
	defer server.Close()
	p := newProvider(State{})
	p.useSingBox, p.httpVersion = true, 3
	p.pass, p.passExpiry = "h3-pass", time.Now().Unix()+3600
	p.selected = Location{Host: host, Port: mustPort(port)}
	if err := p.installRoots(string(pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: tcp.Certificate().Raw}))); err != nil {
		t.Fatal(err)
	}
	p.engine, err = p.newSingRelay()
	if err != nil {
		t.Fatal(err)
	}
	defer p.closeRelays()
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	conn, err := p.openTunnel(ctx, "destination.invalid:443")
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close()
	_ = conn.SetDeadline(time.Now().Add(3 * time.Second))
	if _, err := conn.Write([]byte("quic")); err != nil {
		t.Fatal(err)
	}
	data := make([]byte, 4)
	if _, err := io.ReadFull(conn, data); err != nil {
		t.Fatal(err)
	}
	if string(data) != "quic" {
		t.Fatal("QUIC corrupted payload")
	}

	// An unavailable QUIC edge must fail visibly, never succeed via HTTP/2.
	server.Close()
	udp.Close()
	p.engine.Close()
	p.engine, err = p.newSingRelay()
	if err != nil {
		t.Fatal(err)
	}
	short, stop := context.WithTimeout(ctx, 500*time.Millisecond)
	defer stop()
	if direct, err := p.openTunnel(short, "destination.invalid:443"); err == nil {
		direct.Close()
		t.Fatal("unavailable QUIC unexpectedly succeeded")
	}
}
