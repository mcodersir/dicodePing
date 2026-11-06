package resolver

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net"
	"testing"
	"time"
)

// fakeSOCKS5 serves SOCKS5 CONNECT with a login, and answers each connection
// with the target it asked for, as the proxy got it.
func fakeSOCKS5(t *testing.T, user, password string) string {
	t.Helper()
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = ln.Close() })
	go func() {
		for {
			c, err := ln.Accept()
			if err != nil {
				return
			}
			go func() {
				defer c.Close()
				_ = serveFakeSOCKS5(c, user, password)
			}()
		}
	}()
	return ln.Addr().String()
}

func serveFakeSOCKS5(c net.Conn, user, password string) error {
	b := make([]byte, 512)
	if _, err := io.ReadFull(c, b[:2]); err != nil {
		return err
	}
	if _, err := io.ReadFull(c, b[:b[1]]); err != nil {
		return err
	}
	if _, err := c.Write([]byte{5, 2}); err != nil {
		return err
	}
	// RFC 1929: version, the username, the password.
	if _, err := io.ReadFull(c, b[:2]); err != nil {
		return err
	}
	gotUser := make([]byte, b[1])
	if _, err := io.ReadFull(c, gotUser); err != nil {
		return err
	}
	if _, err := io.ReadFull(c, b[:1]); err != nil {
		return err
	}
	gotPassword := make([]byte, b[0])
	if _, err := io.ReadFull(c, gotPassword); err != nil {
		return err
	}
	if string(gotUser) != user || string(gotPassword) != password {
		_, _ = c.Write([]byte{1, 1})
		return errors.New("bad login")
	}
	if _, err := c.Write([]byte{1, 0}); err != nil {
		return err
	}
	if _, err := io.ReadFull(c, b[:4]); err != nil {
		return err
	}
	if b[3] != 3 {
		return fmt.Errorf("address type %d, not a name", b[3])
	}
	if _, err := io.ReadFull(c, b[:1]); err != nil {
		return err
	}
	name := make([]byte, b[0])
	if _, err := io.ReadFull(c, name); err != nil {
		return err
	}
	if _, err := io.ReadFull(c, b[:2]); err != nil {
		return err
	}
	port := int(b[0])<<8 | int(b[1])
	if _, err := c.Write([]byte{5, 0, 0, 1, 0, 0, 0, 0, 0, 0}); err != nil {
		return err
	}
	_, err := fmt.Fprintf(c, "%s:%d\n", name, port)
	return err
}

// Through the upstream proxy the name goes to the proxy, unresolved, and an
// empty address connects directly again.
func TestDialGoesThroughTheUpstreamProxy(t *testing.T) {
	t.Cleanup(func() { _ = SetUpstreamProxy("", "", "") })
	addr := fakeSOCKS5(t, "u", "p")
	if err := SetUpstreamProxy(addr, "u", "p"); err != nil {
		t.Fatal(err)
	}
	if got := UpstreamProxy(); got != addr {
		t.Fatalf("UpstreamProxy %q", got)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	for name, dial := range map[string]func() (net.Conn, error){
		"Dial":       func() (net.Conn, error) { return Dial(ctx, "tcp", "server.invalid:2499") },
		"DialWithin": func() (net.Conn, error) { return DialWithin(ctx, time.Nanosecond, "tcp", "server.invalid:2499") },
	} {
		c, err := dial()
		if err != nil {
			t.Fatalf("%s: %v", name, err)
		}
		b := make([]byte, 64)
		n, err := c.Read(b)
		_ = c.Close()
		if err != nil {
			t.Fatalf("%s: %v", name, err)
		}
		if got := string(b[:n]); got != "server.invalid:2499\n" {
			t.Fatalf("%s: the proxy got %q", name, got)
		}
	}

	if err := SetUpstreamProxy("", "", ""); err != nil {
		t.Fatal(err)
	}
	if got := UpstreamProxy(); got != "" {
		t.Fatalf("UpstreamProxy %q", got)
	}
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer ln.Close()
	c, err := Dial(ctx, "tcp", ln.Addr().String())
	if err != nil {
		t.Fatalf("direct: %v", err)
	}
	_ = c.Close()
}

// A wrong login, or a proxy that is not there, is an error, not a way around it.
func TestUpstreamProxyFailuresStopTheConnection(t *testing.T) {
	t.Cleanup(func() { _ = SetUpstreamProxy("", "", "") })
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if err := SetUpstreamProxy(fakeSOCKS5(t, "u", "p"), "u", "wrong"); err != nil {
		t.Fatal(err)
	}
	if c, err := Dial(ctx, "tcp", "server.invalid:2499"); err == nil {
		_ = c.Close()
		t.Fatal("a wrong login connected")
	}
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	gone := ln.Addr().String()
	_ = ln.Close()
	if err := SetUpstreamProxy(gone, "", ""); err != nil {
		t.Fatal(err)
	}
	if c, err := Dial(ctx, "tcp", "server.invalid:2499"); err == nil {
		_ = c.Close()
		t.Fatal("a proxy that is not there connected")
	}
}
