package proxy

import (
	"bytes"
	"errors"
	"io"
	"net"
	"net/http"
	"strings"
	"testing"
	"time"
)

func TestHandshakeSOCKS5DomainConnect(t *testing.T) {
	t.Parallel()

	client, server := net.Pipe()
	defer client.Close()
	defer server.Close()

	errCh := make(chan error, 1)
	go func() {
		_, err := client.Write([]byte{socksVersion5, 0x01, socksAuthNoAuth})
		if err != nil {
			errCh <- err
			return
		}

		reply := make([]byte, 2)
		_, err = io.ReadFull(client, reply)
		if err != nil {
			errCh <- err
			return
		}
		if !bytes.Equal(reply, []byte{socksVersion5, socksAuthNoAuth}) {
			errCh <- errors.New("unexpected auth reply")
			return
		}
		_, err = client.Write([]byte{
			socksVersion5, socksCmdConnect, 0x00, socksAtypDomain, 0x0b,
			'e', 'x', 'a', 'm', 'p', 'l', 'e', '.', 'c', 'o', 'm',
			0x01, 0xbb,
		})
		if err != nil {
			errCh <- err
			return
		}
		errCh <- nil
	}()

	target, replyCode, err := handshakeSOCKS5(server)
	if err != nil {
		t.Fatalf("handshakeSOCKS5 returned error: %v", err)
	}
	if replyCode != socksReplySuccess {
		t.Fatalf("expected success code, got %d", replyCode)
	}
	if target != "example.com:443" {
		t.Fatalf("expected target example.com:443, got %q", target)
	}
	if err := <-errCh; err != nil {
		t.Fatalf("client goroutine failed: %v", err)
	}
}

func TestHandshakeSOCKS5RejectsUnsupportedMethod(t *testing.T) {
	t.Parallel()

	client, server := net.Pipe()
	defer client.Close()
	defer server.Close()

	errCh := make(chan error, 1)
	go func() {
		if _, err := client.Write([]byte{socksVersion5, 0x01, 0x02}); err != nil {
			errCh <- err
			return
		}
		reply := make([]byte, 2)
		_, err := io.ReadFull(client, reply)
		if err != nil {
			errCh <- err
			return
		}
		if !bytes.Equal(reply, []byte{socksVersion5, socksAuthNoAccept}) {
			errCh <- errors.New("unexpected auth rejection reply")
			return
		}
		errCh <- nil
	}()

	_, _, err := handshakeSOCKS5(server)
	if err == nil || !strings.Contains(err.Error(), "no supported SOCKS auth methods") {
		t.Fatalf("expected unsupported auth error, got %v", err)
	}
	if err := <-errCh; err != nil {
		t.Fatalf("client goroutine failed: %v", err)
	}
}

func TestHandshakeSOCKS5RejectsUnsupportedCommand(t *testing.T) {
	t.Parallel()

	client, server := net.Pipe()
	defer client.Close()
	defer server.Close()

	go func() {
		_, _ = client.Write([]byte{socksVersion5, 0x01, socksAuthNoAuth})
		reply := make([]byte, 2)
		_, _ = io.ReadFull(client, reply)
		_, _ = client.Write([]byte{
			socksVersion5, 0x03, 0x00, socksAtypIPv4, 127, 0, 0, 1, 0x00, 0x50,
		})
	}()

	_, replyCode, err := handshakeSOCKS5(server)
	if err == nil {
		t.Fatal("expected unsupported command error")
	}
	if replyCode != socksReplyCmdUnsup {
		t.Fatalf("expected command unsupported reply code, got %d", replyCode)
	}
}

func TestSocksServerAllowsConcurrentClients(t *testing.T) {
	t.Parallel()

	server := &SOCKSServer{upstream: &fakeTunnelOpener{delay: 50 * time.Millisecond}}

	runClient := func() error {
		client, conn := net.Pipe()
		defer client.Close()

		done := make(chan struct{})
		go func() {
			server.handleConn(conn)
			close(done)
		}()

		if _, err := client.Write([]byte{socksVersion5, 0x01, socksAuthNoAuth}); err != nil {
			return err
		}

		reply := make([]byte, 12)
		if _, err := io.ReadFull(client, reply[:2]); err != nil {
			return err
		}
		if !bytes.Equal(reply[:2], []byte{socksVersion5, socksAuthNoAuth}) {
			return errors.New("unexpected auth reply")
		}
		if _, err := client.Write([]byte{
			socksVersion5, socksCmdConnect, 0x00, socksAtypDomain, 0x0b,
			'e', 'x', 'a', 'm', 'p', 'l', 'e', '.', 'c', 'o', 'm',
			0x01, 0xbb,
		}); err != nil {
			return err
		}
		if _, err := io.ReadFull(client, reply[:10]); err != nil {
			return err
		}
		if reply[1] != socksReplySuccess {
			return errors.New("unexpected connect reply")
		}

		_ = client.Close()
		<-done
		return nil
	}

	errCh := make(chan error, 2)
	go func() { errCh <- runClient() }()
	go func() { errCh <- runClient() }()

	for i := 0; i < 2; i++ {
		if err := <-errCh; err != nil {
			t.Fatalf("client %d failed: %v", i, err)
		}
	}

	opener := server.upstream.(*fakeTunnelOpener)
	if opener.max.Load() < 2 {
		t.Fatalf("expected concurrent tunnel opens, max=%d", opener.max.Load())
	}
}

func TestSocksServerRejectsWhenConnectionLimitReached(t *testing.T) {
	t.Parallel()

	server := &SOCKSServer{connSlots: make(chan struct{}, 1)}
	server.connSlots <- struct{}{}

	client, conn := net.Pipe()
	defer client.Close()

	done := make(chan struct{})
	go func() {
		server.handleConn(conn)
		close(done)
	}()

	select {
	case <-done:
	case <-time.After(time.Second):
		t.Fatal("server did not reject connection at limit")
	}

	buf := make([]byte, 1)
	if _, err := client.Read(buf); err == nil {
		t.Fatal("expected client side to observe closed connection")
	}
}

func TestSocksServerHandshakeTimeout(t *testing.T) {
	t.Parallel()

	server := &SOCKSServer{handshakeTimeout: 20 * time.Millisecond}
	client, conn := net.Pipe()
	defer client.Close()

	done := make(chan struct{})
	go func() {
		server.handleConn(conn)
		close(done)
	}()

	select {
	case <-done:
	case <-time.After(time.Second):
		t.Fatal("server did not close idle handshake connection")
	}
}

type refusingOpener struct{}

func (refusingOpener) OpenTunnel(string) (net.Conn, error) {
	return nil, &proxyConnectHTTPError{statusCode: http.StatusBadGateway, status: "502 Bad Gateway"}
}

// A port Mozilla's proxy refuses is reported to the client as "not allowed
// by ruleset" (0x02), other failures stay general failures.
func TestSocksServerReportsRefusedPort(t *testing.T) {
	t.Parallel()

	notices := &Notices{}
	server := &SOCKSServer{upstream: refusingOpener{}, Notices: notices}
	for port, want := range map[uint16]byte{9898: socksReplyNotAllow, 443: socksReplyFailure} {
		client, conn := net.Pipe()
		done := make(chan struct{})
		go func() {
			server.handleConn(conn)
			close(done)
		}()
		reply := make([]byte, 10)
		if _, err := client.Write([]byte{socksVersion5, 0x01, socksAuthNoAuth}); err != nil {
			t.Fatal(err)
		}
		if _, err := io.ReadFull(client, reply[:2]); err != nil {
			t.Fatal(err)
		}
		if _, err := client.Write([]byte{socksVersion5, socksCmdConnect, 0x00, socksAtypIPv4, 203, 0, 113, 5, byte(port >> 8), byte(port)}); err != nil {
			t.Fatal(err)
		}
		if _, err := io.ReadFull(client, reply[:10]); err != nil {
			t.Fatal(err)
		}
		if reply[1] != want {
			t.Fatalf("port %d: reply %d, want %d", port, reply[1], want)
		}
		_ = client.Close()
		<-done
	}
	// Only the refused port is a notice for the dashboard.
	got := notices.Since(time.Time{})
	if len(got) != 1 || got[0].Kind != NoticePort || got[0].Detail != "9898" || got[0].Count != 1 || len(got[0].Hosts) != 1 || got[0].Hosts[0] != "203.0.113.5" {
		t.Fatalf("notices %+v", got)
	}
}

// A request for UDP is refused as an unsupported command and noted.
func TestSocksServerNotesUDPRequest(t *testing.T) {
	t.Parallel()

	notices := &Notices{}
	server := &SOCKSServer{upstream: refusingOpener{}, Notices: notices}
	client, conn := net.Pipe()
	done := make(chan struct{})
	go func() {
		server.handleConn(conn)
		close(done)
	}()
	reply := make([]byte, 10)
	if _, err := client.Write([]byte{socksVersion5, 0x01, socksAuthNoAuth}); err != nil {
		t.Fatal(err)
	}
	if _, err := io.ReadFull(client, reply[:2]); err != nil {
		t.Fatal(err)
	}
	if _, err := client.Write([]byte{socksVersion5, 0x03, 0x00, socksAtypIPv4, 0, 0, 0, 0, 0, 0}); err != nil {
		t.Fatal(err)
	}
	if _, err := io.ReadFull(client, reply[:10]); err != nil {
		t.Fatal(err)
	}
	if reply[1] != socksReplyCmdUnsup {
		t.Fatalf("reply %d", reply[1])
	}
	_ = client.Close()
	<-done
	if got := notices.Since(time.Time{}); len(got) != 1 || got[0].Kind != NoticeCommand || got[0].Detail != "UDP" {
		t.Fatalf("notices %+v", got)
	}
}
