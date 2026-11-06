//go:build linux && !android

package egress

import (
	"context"
	"encoding/binary"
	"fmt"
	"net"
	"net/netip"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"syscall"
	"testing"

	"golang.org/x/sys/unix"
)

// realInterface is an interface of this computer other than loopback, for
// routes that must name one.
func realInterface(t *testing.T) net.Interface {
	t.Helper()
	ifaces, err := net.Interfaces()
	if err != nil {
		t.Fatal(err)
	}
	for _, i := range ifaces {
		if i.Flags&net.FlagLoopback == 0 && i.Flags&net.FlagUp != 0 && i.Flags&net.FlagRunning != 0 {
			return i
		}
	}
	t.Skip("no interface but loopback")
	return net.Interface{}
}

// fakeRoutes makes the route files read.
func fakeRoutes(t *testing.T, v4, v6 string) {
	t.Helper()
	dir := t.TempDir()
	old4, old6 := route4File, route6File
	route4File, route6File = filepath.Join(dir, "route"), filepath.Join(dir, "ipv6_route")
	t.Cleanup(func() { route4File, route6File = old4, old6 })
	if err := os.WriteFile(route4File, []byte(v4), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(route6File, []byte(v6), 0o600); err != nil {
		t.Fatal(err)
	}
}

// route4 is a /proc/net/route line: the addresses as the kernel writes
// them, the 32-bit value of their bytes in this machine's order.
func route4(dev, dst, gateway, flags string, metric int, mask string) string {
	h := func(a string) string {
		b := netip.MustParseAddr(a).As4()
		return fmt.Sprintf("%08X", binary.NativeEndian.Uint32(b[:]))
	}
	return fmt.Sprintf("%s\t%s\t%s\t%s\t0\t0\t%d\t%s\t0\t0\t0\n", dev, h(dst), h(gateway), flags, metric, h(mask))
}

func TestLinuxRoutesAreRead(t *testing.T) {
	iface := realInterface(t)
	dev := iface.Name
	v4 := "Iface\tDestination\tGateway\tFlags\tRefCnt\tUse\tMetric\tMask\tMTU\tWindow\tIRTT\n" +
		route4(dev, "0.0.0.0", "192.168.1.1", "0003", 600, "0.0.0.0") +
		route4(dev, "192.168.1.0", "0.0.0.0", "0001", 600, "255.255.255.0") +
		route4("lo", "10.9.0.0", "0.0.0.0", "0001", 0, "255.255.0.0") +
		// Refusing.
		route4(dev, "10.0.0.0", "0.0.0.0", "0201", 0, "255.0.0.0")
	zero := strings.Repeat("0", 32)
	v6 := zero + " 00 " + zero + " 00 fe800000000000000000000000000001 00000400 00000001 00000000 00000003 " + dev + "\n" +
		zero + " 00 " + zero + " 00 " + zero + " ffffffff 00000001 00000000 00200200 lo\n"
	fakeRoutes(t, v4, v6)

	rs := routes(false)
	if len(rs) != 2 {
		t.Fatalf("routes %+v", rs)
	}
	if rs[0].dst != netip.MustParsePrefix("0.0.0.0/0") || rs[0].gateway != netip.MustParseAddr("192.168.1.1") || rs[0].metric != 600 {
		t.Fatalf("default route %+v", rs[0])
	}
	if rs[1].dst != netip.MustParsePrefix("192.168.1.0/24") {
		t.Fatalf("LAN route %+v", rs[1])
	}
	st := &tunState{index: 0xfffffff0}
	if r, ok := defaultRoute(false, st); !ok || r.iface != dev {
		t.Fatalf("default route %+v %t", r, ok)
	}
	if index, ok := defaultInterface(true, st); !ok || index != uint32(iface.Index) {
		t.Fatalf("IPv6 default interface %d %t", index, ok)
	}
	// The TUN's own routes are not the network's.
	if _, ok := defaultRoute(false, &tunState{index: uint32(iface.Index)}); ok {
		t.Fatal("the TUN's interface was taken for the network")
	}
	if index, ok := bestInterface(netip.MustParseAddr("192.168.1.20")); !ok || index != uint32(iface.Index) {
		t.Fatalf("best interface %d %t", index, ok)
	}
	// Only loopback and a refusing route go to 10/8: the default one is
	// taken.
	if index, ok := bestInterface(netip.MustParseAddr("10.9.1.1")); !ok || index != uint32(iface.Index) {
		t.Fatalf("best interface %d %t", index, ok)
	}
}

func TestLinuxDNSServersLeaveOutTheTunsAndLoopback(t *testing.T) {
	iface := realInterface(t)
	dir := t.TempDir()
	resolved, system := filepath.Join(dir, "resolved.conf"), filepath.Join(dir, "resolv.conf")
	if err := os.WriteFile(resolved, []byte("# resolved\nnameserver 192.168.1.1\nnameserver 198.18.0.2\nnameserver 2001:db8::53\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(system, []byte("nameserver 127.0.0.53\noptions edns0\nsearch lan\nnameserver 192.168.1.1\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	old := resolvConfs
	resolvConfs = []string{resolved, system}
	t.Cleanup(func() { resolvConfs = old })
	dev := iface.Name
	fakeRoutes(t, route4(dev, "0.0.0.0", "192.168.1.1", "0003", 100, "0.0.0.0")+
		route4(dev, "192.168.1.0", "0.0.0.0", "0001", 100, "255.255.255.0"), "")

	// 198.18.0.2 has no route to the TUN here, so it is kept.
	got := dnsServers(&tunState{index: 0xfffffff0})
	want := []netip.AddrPort{netip.MustParseAddrPort("192.168.1.1:53"), netip.MustParseAddrPort("198.18.0.2:53"), netip.MustParseAddrPort("[2001:db8::53]:53")}
	if !slices.Equal(got, want) {
		t.Fatalf("servers %v, want %v", got, want)
	}
	// Servers reached through the TUN are left out: here every one (IPv6
	// has no route at all, which keeps it).
	got = dnsServers(&tunState{index: uint32(iface.Index)})
	if len(got) != 1 || got[0] != netip.MustParseAddrPort("[2001:db8::53]:53") {
		t.Fatalf("servers %v", got)
	}
	// None left: the gateway.
	resolvConfs = []string{system + ".missing"}
	got = dnsServers(&tunState{index: 0xfffffff0})
	if len(got) != 1 || got[0] != netip.MustParseAddrPort("192.168.1.1:53") {
		t.Fatalf("servers %v", got)
	}
}

func boundIndex(t *testing.T, c net.Conn) int {
	t.Helper()
	raw, err := c.(syscall.Conn).SyscallConn()
	if err != nil {
		t.Fatal(err)
	}
	var bound int
	var gerr error
	if err := raw.Control(func(fd uintptr) {
		bound, gerr = unix.GetsockoptInt(int(fd), unix.SOL_SOCKET, unix.SO_BINDTOIFINDEX)
	}); err != nil {
		t.Fatal(err)
	}
	if gerr != nil {
		t.Fatal(gerr)
	}
	return bound
}

// A connection made while a TUN runs is bound to the default interface;
// one to this computer is not.
func TestALinuxSocketIsBoundToTheNetwork(t *testing.T) {
	if err := Supported(); err != nil {
		t.Skipf("binding is not allowed here: %v", err)
	}
	index, ok := defaultInterface(false, &tunState{index: 0xfffffff0})
	if !ok {
		t.Skip("no IPv4 default route")
	}
	SetTun(0xfffffff0, 0)
	t.Cleanup(ClearTun)
	// UDP connects without sending anything.
	c, err := DialContext(context.Background(), "udp", "192.0.2.1:9")
	if err != nil {
		t.Fatal(err)
	}
	defer c.Close()
	if bound := boundIndex(t, c); bound != int(index) {
		t.Fatalf("bound to %d, want %d", bound, index)
	}
	l, err := net.ListenPacket("udp4", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer l.Close()
	c2, err := DialContext(context.Background(), "udp", l.LocalAddr().String())
	if err != nil {
		t.Fatal(err)
	}
	defer c2.Close()
	if bound := boundIndex(t, c2); bound != 0 {
		t.Fatalf("a loopback socket is bound to %d", bound)
	}
	// QUIC's socket too.
	u, err := ListenUDP(netip.MustParseAddr("192.0.2.1"))
	if err != nil {
		t.Fatal(err)
	}
	defer u.Close()
	if bound := boundIndex(t, u); bound != int(index) {
		t.Fatalf("the QUIC socket is bound to %d, want %d", bound, index)
	}
}
