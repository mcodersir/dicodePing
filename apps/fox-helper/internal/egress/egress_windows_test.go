package egress

import (
	"context"
	"net"
	"net/netip"
	"syscall"
	"testing"
	"time"

	"golang.org/x/sys/windows"
)

// fakeTun pretends a TUN adapter runs, with an index and LUID no adapter
// has, so the binding works as with one.
func fakeTun(t *testing.T) {
	t.Helper()
	SetTun(0xfffffff0, 0xfffffffffffffff0)
	t.Cleanup(ClearTun)
}

// physicalAddress is an IPv4 address of the default interface, or skips
// the test on a computer without a network.
func physicalAddress(t *testing.T) (uint32, netip.Addr) {
	t.Helper()
	index, ok := physical(false, &tunState{})
	if !ok {
		t.Skip("no IPv4 default route")
	}
	iface, err := net.InterfaceByIndex(int(index))
	if err != nil {
		t.Fatal(err)
	}
	addrs, _ := iface.Addrs()
	for _, a := range addrs {
		if p, err := netip.ParsePrefix(a.String()); err == nil && p.Addr().Is4() {
			return index, p.Addr()
		}
	}
	t.Skip("the default interface has no IPv4 address")
	return 0, netip.Addr{}
}

func TestTheDefaultInterfaceIsFoundAndItsDNSServers(t *testing.T) {
	index, _ := physicalAddress(t)
	if index == 0 {
		t.Fatal("index 0")
	}
	if _, ok := physical(false, &tunState{index: 0xfffffff0, luid: 0xfffffffffffffff0}); !ok {
		t.Fatal("excluding an unknown adapter lost the default route")
	}
	servers := dnsServers(&tunState{})
	if len(servers) == 0 {
		t.Skip("the default interface has no DNS servers")
	}
	for _, s := range servers {
		if s.Port() != 53 || !s.Addr().IsValid() {
			t.Fatalf("server %s", s)
		}
	}
}

// With a TUN, a connection out is pinned to the physical interface.
func TestAConnectionOutIsBound(t *testing.T) {
	index, _ := physicalAddress(t)
	fakeTun(t)
	// UDP connects without sending anything.
	c, err := DialContext(context.Background(), "udp4", "192.0.2.1:9")
	if err != nil {
		t.Fatal(err)
	}
	defer c.Close()
	raw, err := c.(syscall.Conn).SyscallConn()
	if err != nil {
		t.Fatal(err)
	}
	var v int
	var gerr error
	raw.Control(func(fd uintptr) {
		v, gerr = windows.GetsockoptInt(windows.Handle(fd), windows.IPPROTO_IP, ipUnicastIf)
	})
	if gerr != nil {
		t.Fatal(gerr)
	}
	// Set in network byte order, read back in the machine's.
	if uint32(v) != index {
		t.Fatalf("bound to %d, want %d", v, index)
	}
}

// A connection to this computer's own address never leaves it: it is not
// bound, and connects.
func TestAConnectionToThisComputerConnects(t *testing.T) {
	_, addr := physicalAddress(t)
	ln, err := net.Listen("tcp4", netip.AddrPortFrom(addr, 0).String())
	if err != nil {
		t.Fatal(err)
	}
	defer ln.Close()
	go func() {
		if c, err := ln.Accept(); err == nil {
			c.Write([]byte("ok"))
			c.Close()
		}
	}()
	fakeTun(t)
	conn, err := Dialer(5*time.Second).DialContext(context.Background(), "tcp", ln.Addr().String())
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close()
	buf := make([]byte, 2)
	if _, err := conn.Read(buf); err != nil || string(buf) != "ok" {
		t.Fatalf("read %q %v", buf, err)
	}
}

func TestLoopbackIsLeftAlone(t *testing.T) {
	ln, err := net.Listen("tcp4", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer ln.Close()
	go func() {
		if c, err := ln.Accept(); err == nil {
			c.Close()
		}
	}()
	fakeTun(t)
	conn, err := DialContext(context.Background(), "tcp", ln.Addr().String())
	if err != nil {
		t.Fatal(err)
	}
	conn.Close()
}

func TestAUDPSocketForQUICIsBound(t *testing.T) {
	index, _ := physicalAddress(t)
	fakeTun(t)
	uc, err := ListenUDP(netip.MustParseAddr("192.0.2.1"))
	if err != nil {
		t.Fatal(err)
	}
	defer uc.Close()
	if a := uc.LocalAddr().(*net.UDPAddr); a.IP.To4() == nil {
		t.Fatalf("an IPv4 destination got a socket at %s", a)
	}
	raw, err := uc.SyscallConn()
	if err != nil {
		t.Fatal(err)
	}
	var v int
	var gerr error
	raw.Control(func(fd uintptr) {
		v, gerr = windows.GetsockoptInt(windows.Handle(fd), windows.IPPROTO_IP, ipUnicastIf)
	})
	if gerr != nil || uint32(v) != index {
		t.Fatalf("bound to %d (%v), want %d", v, gerr, index)
	}
}

// Names still resolve while a TUN runs: the hosts file, and localhost.
func TestNamesResolveWhileATUNRuns(t *testing.T) {
	fakeTun(t)
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	addrs, err := LookupNetIP(ctx, "localhost")
	if err != nil || len(addrs) == 0 {
		t.Fatalf("localhost: %v %v", addrs, err)
	}
}

func TestWithoutATUNNothingIsBound(t *testing.T) {
	ClearTun()
	if _, _, ok := Tun(); ok {
		t.Fatal("a TUN is set")
	}
	d := Dialer(time.Second)
	if d.Resolver != nil {
		t.Fatal("the system resolver is replaced without a TUN")
	}
	if err := Control("tcp4", "1.2.3.4:443", nil); err != nil {
		t.Fatalf("control without a TUN: %v", err)
	}
}
