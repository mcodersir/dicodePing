package proxy

import (
	"context"
	"net"
	"slices"
	"testing"
	"time"
)

func TestUpstreamStepsFollowIPVersion(t *testing.T) {
	t.Cleanup(func() { SetUpstreamIPVersion("auto") })
	for version, want := range map[string][]string{
		"auto":       {stepIPv4, stepIPv6},
		"":           {stepIPv4, stepIPv6},
		"dual":       {stepBoth},
		"ipv6_first": {stepIPv6, stepIPv4},
		"ipv4":       {stepIPv4},
		"ipv6":       {stepIPv6},
	} {
		SetUpstreamIPVersion(version)
		if got := upstreamSteps(); !slices.Equal(got, want) {
			t.Errorf("%q: %v, want %v", version, got, want)
		}
	}
}

// The server listens on ::1 alone; the system resolver gives localhost's
// 127.0.0.1 and ::1. Every mode that lets IPv6 in reaches it (auto after
// IPv4 fails); IPv4 alone does not.
func TestDialUpstreamFollowsIPVersion(t *testing.T) {
	ln, err := net.Listen("tcp6", "[::1]:0")
	if err != nil {
		t.Skipf("no IPv6 loopback here: %v", err)
	}
	defer ln.Close()
	go func() {
		for {
			c, err := ln.Accept()
			if err != nil {
				return
			}
			c.Close()
		}
	}()
	_, port, _ := net.SplitHostPort(ln.Addr().String())
	address := net.JoinHostPort("localhost", port)
	t.Cleanup(func() { SetUpstreamIPVersion("auto") })

	for version, wantOK := range map[string]bool{"auto": true, "dual": true, "ipv6_first": true, "ipv4": false, "ipv6": true} {
		SetUpstreamIPVersion(version)
		ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		conn, err := dialUpstream(ctx, address)
		cancel()
		if (err == nil) != wantOK {
			t.Errorf("%s: dial = %v, want ok=%v", version, err, wantOK)
		}
		if conn != nil {
			if ip := conn.RemoteAddr().(*net.TCPAddr).IP; ip.To4() != nil {
				t.Errorf("%s: connected to %s, want ::1", version, ip)
			}
			conn.Close()
		}
	}
}

func TestStepErrorKeepsTheIPv4One(t *testing.T) {
	var e stepError
	e.note(stepIPv6, context.DeadlineExceeded)
	e.note(stepIPv4, net.ErrClosed)
	if e.err() != net.ErrClosed {
		t.Fatalf("err = %v, want the IPv4 one", e.err())
	}
}
