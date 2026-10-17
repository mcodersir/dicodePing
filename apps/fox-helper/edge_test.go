package main

import (
	"context"
	"crypto/x509"
	"encoding/binary"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

func TestSecureDNSValidatesAnswersAndRejectsTruncation(t *testing.T) {
	query, err := dnsQuestion("relay.example.com")
	if err != nil {
		t.Fatal(err)
	}
	reply := append([]byte(nil), query...)
	reply[2] = 0x81
	reply[3] = 0x80
	reply[7] = 1
	reply = append(reply, 0xc0, 0x0c, 0, 1, 0, 1, 0, 0, 0, 60, 0, 4, 203, 0, 113, 8)
	ips, err := dnsAddresses(query, reply)
	if err != nil || len(ips) != 1 || ips[0].String() != "203.0.113.8" {
		t.Fatal(ips, err)
	}
	for n := 0; n < len(reply); n++ {
		if _, err := dnsAddresses(query, reply[:n]); err == nil {
			t.Fatalf("accepted truncated reply %d", n)
		}
	}
	reply[0] ^= 1
	if _, err := dnsAddresses(query, reply); err == nil {
		t.Fatal("accepted mismatched DNS transaction")
	}
	reply[0] ^= 1
	copy(reply[len(reply)-4:], []byte{127, 0, 0, 1})
	if _, err := dnsAddresses(query, reply); err == nil {
		t.Fatal("accepted loopback relay address")
	}
	reply[len(query)] = 0xff
	reply[len(query)+1] = 0xff
	if _, err := dnsAddresses(query, reply); err == nil {
		t.Fatal("accepted out-of-bounds name pointer")
	}
}

func TestEdgeBootstrapPreservesVerifiedTLSNameAndHTTP2(t *testing.T) {
	upstream := httptest.NewUnstartedServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.ProtoMajor != 2 {
			t.Error("HTTP/2 was not negotiated")
		}
		w.Write([]byte("relay-ok"))
	}))
	upstream.EnableHTTP2 = true
	upstream.StartTLS()
	defer upstream.Close()
	_, port, _ := net.SplitHostPort(upstream.Listener.Addr().String())
	roots := x509.NewCertPool()
	roots.AddCert(upstream.Certificate())
	p := newProvider(State{})
	p.roots = roots
	p.edgeResolver = func(context.Context, string) ([]net.IP, error) { return []net.IP{net.IPv4(127, 0, 0, 1)}, nil }
	transport := &http.Transport{ForceAttemptHTTP2: true, DialTLSContext: p.dialEdgeTLS}
	defer transport.CloseIdleConnections()
	client := &http.Client{Transport: transport, Timeout: time.Second * 3}
	name := upstream.Certificate().DNSNames[0]
	resp, err := client.Get("https://" + net.JoinHostPort(name, port))
	if err != nil {
		t.Fatal(err)
	}
	body, _ := io.ReadAll(resp.Body)
	resp.Body.Close()
	if string(body) != "relay-ok" || resp.ProtoMajor != 2 {
		t.Fatal("relay request failed")
	}
	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	if conn, err := p.dialEdgeTLS(ctx, "tcp", net.JoinHostPort("wrong.invalid", port)); err == nil {
		conn.Close()
		t.Fatal("DNS address override bypassed TLS certificate verification")
	}
}

func FuzzDNSResponse(f *testing.F) {
	query, _ := dnsQuestion("relay.example.com")
	f.Add(query)
	f.Fuzz(func(t *testing.T, packet []byte) {
		if len(packet) >= 2 {
			binary.BigEndian.PutUint16(packet, binary.BigEndian.Uint16(query))
		}
		_, _ = dnsAddresses(query, packet)
	})
}
