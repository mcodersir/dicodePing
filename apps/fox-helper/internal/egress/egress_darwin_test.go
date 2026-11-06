package egress

import (
	"context"
	"net"
	"net/netip"
	"slices"
	"syscall"
	"testing"

	"golang.org/x/sys/unix"
)

func TestDHCPServersAreRead(t *testing.T) {
	packet := "op = BOOTREPLY\nhtype = 1\nyiaddr = 192.168.1.20\noptions:\n" +
		"Options count is 9\n" +
		"router (ip_mult): {192.168.1.1}\n" +
		"domain_name_server (ip_mult): {192.168.1.1, 8.8.8.8}\n" +
		"end (none):\n"
	got := dhcpServers(packet)
	want := []netip.Addr{netip.MustParseAddr("192.168.1.1"), netip.MustParseAddr("8.8.8.8")}
	if !slices.Equal(got, want) {
		t.Fatalf("got %v, want %v", got, want)
	}
	if got := dhcpServers("op = BOOTREPLY\n"); len(got) != 0 {
		t.Fatalf("got %v from a packet without servers", got)
	}
}

func TestTheMacDefaultRouteAndItsLookupAgree(t *testing.T) {
	st := &tunState{index: 0xfffffff0}
	index, ok := defaultInterface(false, st)
	if !ok {
		t.Skip("no IPv4 default route")
	}
	best, ok := bestInterface(netip.MustParseAddr("192.0.2.1"))
	if !ok || best != index {
		t.Fatalf("the route to 192.0.2.1 is through %d (%t), the default route through %d", best, ok, index)
	}
	if _, ok := defaultInterface(false, &tunState{index: index}); ok {
		t.Fatal("the TUN's interface was taken for the network")
	}
	t.Logf("default interface %d, DNS %v", index, dnsServers(st))
}

// A connection made while a TUN runs is bound to the default interface;
// one to this computer is not.
func TestAMacSocketIsBoundToTheNetwork(t *testing.T) {
	index, ok := defaultInterface(false, &tunState{index: 0xfffffff0})
	if !ok {
		t.Skip("no IPv4 default route")
	}
	SetTun(0xfffffff0, 0)
	t.Cleanup(ClearTun)
	bound := func(c net.Conn) int {
		raw, err := c.(syscall.Conn).SyscallConn()
		if err != nil {
			t.Fatal(err)
		}
		var v int
		var gerr error
		raw.Control(func(fd uintptr) { v, gerr = unix.GetsockoptInt(int(fd), unix.IPPROTO_IP, unix.IP_BOUND_IF) })
		if gerr != nil {
			t.Fatal(gerr)
		}
		return v
	}
	c, err := DialContext(context.Background(), "udp4", "192.0.2.1:9")
	if err != nil {
		t.Fatal(err)
	}
	defer c.Close()
	if got := bound(c); got != int(index) {
		t.Fatalf("bound to %d, want %d", got, index)
	}
	l, err := net.ListenPacket("udp4", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer l.Close()
	c2, err := DialContext(context.Background(), "udp4", l.LocalAddr().String())
	if err != nil {
		t.Fatal(err)
	}
	defer c2.Close()
	if got := bound(c2); got != 0 {
		t.Fatalf("a loopback socket is bound to %d", got)
	}
}
