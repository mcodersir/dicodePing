package main

import (
	"context"
	"crypto/tls"
	"crypto/x509"
	"encoding/binary"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"sync/atomic"
	"testing"
	"time"
)

// Browser and messenger streams must not starve the next SOCKS connection.
func TestSOCKSMoreThan64LiveStreamsContinueExchangingData(t *testing.T) {
	edge := httptest.NewUnstartedServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(200)
		w.(http.Flusher).Flush()
		buf := make([]byte, 4096)
		for {
			n, err := r.Body.Read(buf)
			if n > 0 {
				w.Write(buf[:n])
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
	roots := x509.NewCertPool()
	roots.AddCert(edge.Certificate())
	host, port, _ := net.SplitHostPort(edge.Listener.Addr().String())
	p := newProvider(State{})
	p.pass = "test"
	p.passExpiry = time.Now().Unix() + 3600
	p.selected = Location{Host: host, Port: mustPort(port)}
	p.roots = roots
	p.streams = p.relayTransport()
	p.listener, _ = net.Listen("tcp", "127.0.0.1:0")
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() { done <- p.serve(ctx) }()
	var conns []net.Conn
	defer func() {
		for _, c := range conns {
			c.Close()
		}
		cancel()
		select {
		case <-done:
		case <-time.After(3 * time.Second):
			t.Error("relay shutdown stuck")
		}
	}()
	for i := 0; i < 80; i++ {
		c, err := net.DialTimeout("tcp", p.listener.Addr().String(), time.Second)
		if err != nil {
			t.Fatal(err)
		}
		conns = append(conns, c)
		c.SetDeadline(time.Now().Add(2 * time.Second))
		c.Write([]byte{5, 1, 0})
		response := make([]byte, 2)
		if _, err = io.ReadFull(c, response); err != nil {
			t.Fatalf("live stream %d stalled at SOCKS greeting: %v", i+1, err)
		}
		req := []byte{5, 1, 0, 3, byte(len("example.invalid"))}
		req = append(req, []byte("example.invalid")...)
		req = binary.BigEndian.AppendUint16(req, 443)
		c.Write(req)
		reply := make([]byte, 10)
		if _, err = io.ReadFull(c, reply); err != nil || reply[1] != 0 {
			t.Fatalf("CONNECT %d: %v %v", i+1, reply, err)
		}
		c.SetDeadline(time.Time{})
	}
	for round := 0; round < 2; round++ {
		for i, c := range conns {
			c.SetDeadline(time.Now().Add(2 * time.Second))
			payload := make([]byte, 32*1024)
			payload[0] = byte(i)
			payload[1] = byte(round)
			written := make(chan error, 1)
			go func() { _, err := c.Write(payload); written <- err }()
			got := make([]byte, len(payload))
			if _, err := io.ReadFull(c, got); err != nil || got[0] != byte(i) || got[1] != byte(round) {
				t.Fatalf("payload %d/%d: %v", round, i, err)
			}
			if err := <-written; err != nil {
				t.Fatal(err)
			}
			c.SetDeadline(time.Time{})
		}
		if round == 0 {
			time.Sleep(17 * time.Second)
		}
	}
}

func TestBackgroundPassRefreshDoesNotBlockWorkingPass(t *testing.T) {
	started := make(chan struct{})
	release := make(chan struct{})
	var calls atomic.Int32
	guardian := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls.Add(1)
		close(started)
		<-release
		w.WriteHeader(503)
	}))
	defer guardian.Close()
	p := newProvider(State{AccessToken: "access", ExpiresAt: time.Now().Unix() + 3600})
	p.guardianURL = guardian.URL
	p.pass = "working"
	p.passExpiry = time.Now().Unix() + 3600
	done := make(chan error, 1)
	go func() { done <- p.refreshProxyPass(context.Background(), true) }()
	<-started
	ctx, cancel := context.WithTimeout(context.Background(), 200*time.Millisecond)
	defer cancel()
	pass, err := p.proxyPass(ctx)
	close(release)
	refreshErr := <-done
	if err != nil || pass != "working" || refreshErr == nil || p.pass != "working" || calls.Load() != 1 {
		t.Fatalf("working pass damaged/blocked by metadata refresh: %q %v %v", pass, err, refreshErr)
	}
}

type droppedReadConn struct {
	net.Conn
	drop *atomic.Bool
}

func (c *droppedReadConn) Read(b []byte) (int, error) {
	for {
		n, err := c.Conn.Read(b)
		if err != nil || !c.drop.Load() {
			return n, err
		}
	}
}

func TestSilentHTTP2EdgeIsEvictedAndNewTrafficRecovers(t *testing.T) {
	edge := httptest.NewUnstartedServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(200)
		w.(http.Flusher).Flush()
		buf := make([]byte, 1024)
		for {
			n, err := r.Body.Read(buf)
			if n > 0 {
				w.Write(buf[:n])
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
	roots := x509.NewCertPool()
	roots.AddCert(edge.Certificate())
	host, port, _ := net.SplitHostPort(edge.Listener.Addr().String())
	p := newProvider(State{})
	p.roots = roots
	p.pass = "valid"
	p.passExpiry = time.Now().Unix() + 3600
	p.selected = Location{Host: host, Port: mustPort(port)}
	p.streams = p.relayTransport()
	defer p.streams.CloseIdleConnections()
	// Speed up the same production HTTP/2 health policy for deterministic testing.
	p.streams.HTTP2.SendPingTimeout = 100 * time.Millisecond
	p.streams.HTTP2.PingTimeout = 100 * time.Millisecond
	var drop atomic.Bool
	var dials atomic.Int32
	p.streams.DialTLSContext = func(ctx context.Context, network, address string) (net.Conn, error) {
		c, err := (&net.Dialer{}).DialContext(ctx, network, address)
		if err != nil {
			return nil, err
		}
		if dials.Add(1) == 1 {
			c = &droppedReadConn{Conn: c, drop: &drop}
		}
		secure := tls.Client(c, &tls.Config{RootCAs: roots, ServerName: host, NextProtos: []string{"h2"}})
		if err = secure.HandshakeContext(ctx); err != nil {
			c.Close()
			return nil, err
		}
		return secure, nil
	}
	ctx, cancel := context.WithTimeout(context.Background(), 4*time.Second)
	defer cancel()
	first, err := p.openTunnel(ctx, "example.invalid:443")
	if err != nil {
		t.Fatal(err)
	}
	defer first.Close()
	exchange := func(c net.Conn) {
		t.Helper()
		written := make(chan error, 1)
		go func() { _, e := c.Write([]byte("real bytes")); written <- e }()
		buf := make([]byte, 10)
		if _, err := io.ReadFull(c, buf); err != nil || string(buf) != "real bytes" {
			t.Fatalf("payload: %q %v", buf, err)
		}
		if err := <-written; err != nil {
			t.Fatal(err)
		}
	}
	exchange(first)
	drop.Store(true)
	first.Write([]byte("lost"))
	buf := make([]byte, 4)
	if _, err = first.Read(buf); err == nil || ctx.Err() != nil {
		t.Fatalf("silent edge was not evicted before deadline: %v", err)
	}
	second, err := p.openTunnel(ctx, "example.invalid:443")
	if err != nil {
		t.Fatal(err)
	}
	defer second.Close()
	exchange(second)
	if dials.Load() < 2 {
		t.Fatal("dead transport reused")
	}
}

func TestExpiredPassWaiterCanCancelWithoutBlockingOthers(t *testing.T) {
	p := newProvider(State{})
	p.passRefresh <- struct{}{}
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Millisecond)
	defer cancel()
	if _, err := p.proxyPass(ctx); err != context.DeadlineExceeded {
		t.Fatalf("waiter ignored cancellation: %v", err)
	}
	<-p.passRefresh
}

func TestRequestThrottleDoesNotReportQuotaExhaustion(t *testing.T) {
	for _, remaining := range []string{"", "1234", "0"} {
		headers := http.Header{}
		if remaining != "" {
			headers.Set("X-Quota-Remaining", remaining)
		}
		err := proxyLimitError(headers)
		if (err.Code == "quota_exceeded") != (remaining == "0") {
			t.Fatalf("temporary limit killed account: remaining=%q error=%v", remaining, err)
		}
	}
}
