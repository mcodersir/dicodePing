package proxy

import (
	"io"
	"net"
	"testing"
	"time"
)

// A full listener must queue the next SOCKS handshake, not close it and
// trigger the VPN bridge's reconnect loop.
func TestSOCKSListenerBackpressure(t *testing.T) {
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer ln.Close()
	s := NewSOCKSServer(nil, 3*time.Second, time.Second, 1)
	go ServeSOCKS(ln, s)
	first, err := net.Dial("tcp", ln.Addr().String())
	if err != nil {
		t.Fatal(err)
	}
	defer first.Close()
	if _, err = first.Write([]byte{5, 1, 0}); err != nil {
		t.Fatal(err)
	}
	if _, err = io.ReadFull(first, make([]byte, 2)); err != nil {
		t.Fatal(err)
	}
	second, err := net.Dial("tcp", ln.Addr().String())
	if err != nil {
		t.Fatal(err)
	}
	defer second.Close()
	second.Write([]byte{5, 1, 0})
	second.SetReadDeadline(time.Now().Add(100 * time.Millisecond))
	_, err = second.Read(make([]byte, 2))
	if e, ok := err.(net.Error); !ok || !e.Timeout() {
		t.Fatalf("pending handshake must wait, not be rejected: %v", err)
	}
	first.Close()
	second.SetReadDeadline(time.Now().Add(time.Second))
	reply := make([]byte, 2)
	if _, err = io.ReadFull(second, reply); err != nil {
		t.Fatalf("queued client not admitted: %v", err)
	}
	if reply[0] != 5 || reply[1] != 0 {
		t.Fatalf("bad greeting: %v", reply)
	}
}

func TestLoopbackBridgeRotatesWhileLANClientsKeepAffinity(t *testing.T) {
	if got := clientAffinityKey(&net.TCPAddr{IP: net.ParseIP("127.0.0.1"), Port: 54321}); got != "" {
		t.Fatal(got)
	}
	if got := clientAffinityKey(&net.TCPAddr{IP: net.ParseIP("192.168.1.7"), Port: 54321}); got != "192.168.1.7" {
		t.Fatal(got)
	}
}
