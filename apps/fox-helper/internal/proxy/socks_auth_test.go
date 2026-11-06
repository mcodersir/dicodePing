package proxy

import (
	"errors"
	"io"
	"net"
	"testing"
	"time"
)

// runHandshake drives a client script against handshakeSOCKS5Auth.
func runHandshake(t *testing.T, auth *socksCredentials, client func(c net.Conn)) (string, error) {
	t.Helper()
	server, clientConn := net.Pipe()
	defer server.Close()
	defer clientConn.Close()
	_ = server.SetDeadline(time.Now().Add(3 * time.Second))
	_ = clientConn.SetDeadline(time.Now().Add(3 * time.Second))
	go client(clientConn)
	target, _, err := handshakeSOCKS5Auth(server, auth)
	return target, err
}

func expectBytes(t *testing.T, c net.Conn, want []byte) {
	t.Helper()
	got := make([]byte, len(want))
	if _, err := io.ReadFull(c, got); err != nil {
		t.Errorf("reading %v: %v", want, err)
		return
	}
	for i := range want {
		if got[i] != want[i] {
			t.Errorf("got %v, want %v", got, want)
			return
		}
	}
}

func userPassMessage(user, pass string) []byte {
	msg := []byte{socksUserPassVer, byte(len(user))}
	msg = append(msg, user...)
	msg = append(msg, byte(len(pass)))
	return append(msg, pass...)
}

var connectExample = []byte{socksVersion5, socksCmdConnect, 0x00, socksAtypDomain, 11, 'e', 'x', 'a', 'm', 'p', 'l', 'e', '.', 'c', 'o', 'm', 0x01, 0xbb}

func TestSOCKSUsernamePassword(t *testing.T) {
	auth := SOCKSCredentials("alice", "s3cret")

	target, err := runHandshake(t, auth, func(c net.Conn) {
		_, _ = c.Write([]byte{socksVersion5, 2, socksAuthNoAuth, socksAuthUserPass})
		expectBytes(t, c, []byte{socksVersion5, socksAuthUserPass})
		_, _ = c.Write(userPassMessage("alice", "s3cret"))
		expectBytes(t, c, []byte{socksUserPassVer, 0x00})
		_, _ = c.Write(connectExample)
	})
	if err != nil || target != "example.com:443" {
		t.Fatalf("valid login: %q %v", target, err)
	}

	_, err = runHandshake(t, auth, func(c net.Conn) {
		_, _ = c.Write([]byte{socksVersion5, 1, socksAuthUserPass})
		expectBytes(t, c, []byte{socksVersion5, socksAuthUserPass})
		_, _ = c.Write(userPassMessage("alice", "wrong"))
		expectBytes(t, c, []byte{socksUserPassVer, 0x01})
	})
	if !errors.Is(err, errSOCKSAuth) {
		t.Fatalf("wrong password: %v", err)
	}

	_, err = runHandshake(t, auth, func(c net.Conn) {
		_, _ = c.Write([]byte{socksVersion5, 1, socksAuthNoAuth})
		expectBytes(t, c, []byte{socksVersion5, socksAuthNoAccept})
	})
	if !errors.Is(err, errSOCKSAuth) {
		t.Fatalf("a client without credentials must be refused: %v", err)
	}

	// Without configured credentials nothing changes.
	target, err = runHandshake(t, nil, func(c net.Conn) {
		_, _ = c.Write([]byte{socksVersion5, 1, socksAuthNoAuth})
		expectBytes(t, c, []byte{socksVersion5, socksAuthNoAuth})
		_, _ = c.Write(connectExample)
	})
	if err != nil || target != "example.com:443" {
		t.Fatalf("no auth: %q %v", target, err)
	}
	if SOCKSCredentials("", "") != nil {
		t.Fatal("empty settings mean no authentication")
	}
}
