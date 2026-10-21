package main

import (
	"bytes"
	"context"
	"crypto/tls"
	"io"
	"net"
	"net/http"
	"sync"
	"testing"
)

type captureHello struct {
	net.Conn
	writes [][]byte
}

func (c *captureHello) Write(b []byte) (int, error) {
	c.writes = append(c.writes, append([]byte(nil), b...))
	return len(b), nil
}
func (c *captureHello) Read(b []byte) (int, error) { return 0, io.EOF }

func TestHelloSplitsSNIWithoutChangingBytes(t *testing.T) {
	for _, mode := range []string{"sni", "first_byte", "off"} {
		raw := &captureHello{}
		client := tls.Client(raw, &tls.Config{ServerName: "firefox.settings.services.mozilla.com"})
		_ = client.HandshakeContext(context.Background())
		hello := bytes.Join(raw.writes, nil)
		if sniStart(hello) < 0 {
			t.Fatal("real ClientHello SNI was not found")
		}
		target := &captureHello{}
		split := &helloSplitConn{Conn: target, mode: mode}
		if n, err := split.Write(hello); err != nil || n != len(hello) {
			t.Fatalf("%s: %d %v", mode, n, err)
		}
		if !bytes.Equal(bytes.Join(target.writes, nil), hello) {
			t.Fatal("TLS ClientHello was corrupted")
		}
		if mode == "sni" && len(target.writes[0]) != sniStart(hello) {
			t.Fatal("did not split at SNI")
		}
		expected := 3
		if mode == "off" {
			expected = 1
		}
		if len(target.writes) != expected {
			t.Fatal(mode, len(target.writes))
		}
		_, _ = split.Write([]byte("application-record"))
		if len(target.writes) != expected+1 {
			t.Fatal("split an application record")
		}
	}
}
func TestMalformedHelloNeverPanics(t *testing.T) {
	for n := 0; n < 512; n++ {
		b := bytes.Repeat([]byte{255}, n)
		if n > 5 {
			b[0] = 22
			b[5] = 1
		}
		_ = sniStart(b)
	}
}
func TestParallelRelayCarriersDoNotShareAllStreams(t *testing.T) {
	p := &provider{relayPool: []*http.Transport{{}, {}, {}, {}}}
	counts := sync.Map{}
	var wg sync.WaitGroup
	for i := 0; i < 80; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			tr := p.nextRelay()
			v, _ := counts.LoadOrStore(tr, new(sync.Mutex))
			lock := v.(*sync.Mutex)
			lock.Lock()
			lock.Unlock()
		}()
	}
	wg.Wait()
	n := 0
	counts.Range(func(_, _ any) bool { n++; return true })
	if n != 4 {
		t.Fatal(n)
	}
	cfg := relayHTTP2Config()
	if cfg.PingTimeout.Seconds() != 25 || cfg.WriteByteTimeout.Seconds() != 60 {
		t.Fatal("mobile handoff tolerance regressed")
	}
}
