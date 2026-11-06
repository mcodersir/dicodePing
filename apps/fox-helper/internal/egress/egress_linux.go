//go:build linux && !android

package egress

import (
	"encoding/binary"
	"encoding/hex"
	"errors"
	"math/bits"
	"net"
	"net/netip"
	"os"
	"strconv"
	"strings"
	"syscall"

	"golang.org/x/sys/unix"
)

// On Linux the TUN's routes are in a table of their own, which rules send
// every connection to but those from a socket bound to an interface (and
// replies, which leave from the address they came to). The main table
// keeps the system's routes, which are read from /proc.

// Route flags (linux/route.h).
const (
	rtfUp     = 0x0001
	rtfReject = 0x0200
)

// sysRoute is a route of the system's.
type sysRoute struct {
	iface   string
	dst     netip.Prefix
	gateway netip.Addr
	metric  uint64
}

// Replaced in tests.
var (
	route4File = "/proc/net/route"
	route6File = "/proc/net/ipv6_route"
)

// routes reads the routes of a family: IPv4's of the main table, IPv6's of
// all; not those through loopback (unreachable entries) or refusing.
func routes(v6 bool) []sysRoute {
	path, parse := route4File, parseRoute4
	if v6 {
		path, parse = route6File, parseRoute6
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return nil
	}
	var out []sysRoute
	for _, line := range strings.Split(string(data), "\n") {
		if r, ok := parse(strings.Fields(line)); ok && r.iface != "lo" {
			out = append(out, r)
		}
	}
	return out
}

// parseRoute4 reads a /proc/net/route line: Iface Destination Gateway
// Flags RefCnt Use Metric Mask ..., the addresses in hex in the kernel's
// byte order.
func parseRoute4(f []string) (sysRoute, bool) {
	if len(f) < 8 {
		return sysRoute{}, false
	}
	flags, err := strconv.ParseUint(f[3], 16, 32)
	if err != nil || flags&rtfUp == 0 || flags&rtfReject != 0 {
		return sysRoute{}, false
	}
	dst, ok1 := hexAddr4(f[1])
	gateway, ok2 := hexAddr4(f[2])
	mask, ok3 := hexAddr4(f[7])
	metric, err := strconv.ParseUint(f[6], 10, 32)
	if !ok1 || !ok2 || !ok3 || err != nil {
		return sysRoute{}, false
	}
	m := mask.As4()
	return sysRoute{iface: f[0], dst: netip.PrefixFrom(dst, bits.OnesCount32(binary.BigEndian.Uint32(m[:]))), gateway: gateway, metric: metric}, true
}

func hexAddr4(s string) (netip.Addr, bool) {
	v, err := strconv.ParseUint(s, 16, 32)
	if err != nil {
		return netip.Addr{}, false
	}
	var b [4]byte
	binary.NativeEndian.PutUint32(b[:], uint32(v))
	return netip.AddrFrom4(b), true
}

// parseRoute6 reads a /proc/net/ipv6_route line: Destination PrefixLen
// Source SourcePrefixLen NextHop Metric RefCnt Use Flags Iface, in hex.
func parseRoute6(f []string) (sysRoute, bool) {
	if len(f) < 10 {
		return sysRoute{}, false
	}
	flags, err := strconv.ParseUint(f[8], 16, 32)
	if err != nil || flags&rtfUp == 0 || flags&rtfReject != 0 {
		return sysRoute{}, false
	}
	dst, ok1 := hexAddr6(f[0])
	gateway, ok2 := hexAddr6(f[4])
	length, err1 := strconv.ParseUint(f[1], 16, 8)
	metric, err2 := strconv.ParseUint(f[5], 16, 32)
	if !ok1 || !ok2 || err1 != nil || err2 != nil || length > 128 {
		return sysRoute{}, false
	}
	return sysRoute{iface: f[9], dst: netip.PrefixFrom(dst, int(length)), gateway: gateway, metric: metric}, true
}

func hexAddr6(s string) (netip.Addr, bool) {
	b, err := hex.DecodeString(s)
	if err != nil || len(b) != 16 {
		return netip.Addr{}, false
	}
	return netip.AddrFrom16([16]byte(b)), true
}

// defaultInterface is the interface of the default route with the lowest
// metric whose interface is up and is not the TUN adapter.
func defaultInterface(v6 bool, st *tunState) (uint32, bool) {
	r, ok := defaultRoute(v6, st)
	if !ok {
		return 0, false
	}
	iface, err := net.InterfaceByName(r.iface)
	if err != nil {
		return 0, false
	}
	return uint32(iface.Index), true
}

func defaultRoute(v6 bool, st *tunState) (sysRoute, bool) {
	var best sysRoute
	found := false
	for _, r := range routes(v6) {
		if r.dst.Bits() != 0 || (found && r.metric >= best.metric) {
			continue
		}
		iface, err := net.InterfaceByName(r.iface)
		if err != nil || uint32(iface.Index) == st.index || !interfaceUp(iface.Index) {
			continue
		}
		best, found = r, true
	}
	return best, found
}

// bestInterface is the interface of the most specific route to dst (of
// the lowest metric among equals); a link-local address's own.
func bestInterface(dst netip.Addr) (uint32, bool) {
	if zone := dst.Zone(); zone != "" {
		if iface, err := net.InterfaceByName(zone); err == nil {
			return uint32(iface.Index), true
		}
		if index, err := strconv.Atoi(zone); err == nil {
			return uint32(index), true
		}
	}
	var best sysRoute
	found := false
	for _, r := range routes(dst.Is6()) {
		if !r.dst.Contains(dst.WithZone("")) {
			continue
		}
		if found && (r.dst.Bits() < best.dst.Bits() || (r.dst.Bits() == best.dst.Bits() && r.metric >= best.metric)) {
			continue
		}
		best, found = r, true
	}
	if !found {
		return 0, false
	}
	iface, err := net.InterfaceByName(best.iface)
	if err != nil {
		return 0, false
	}
	return uint32(iface.Index), true
}

// bind binds the socket to interface index, which takes it out of the
// TUN's rules. Without root Linux allows it from 5.7 on (Supported).
func bind(c syscall.RawConn, _ bool, index uint32) error {
	var opErr error
	err := c.Control(func(fd uintptr) { opErr = bindToInterface(int(fd), index) })
	if err != nil {
		return err
	}
	return opErr
}

func bindToInterface(fd int, index uint32) error {
	err := unix.SetsockoptInt(fd, unix.SOL_SOCKET, unix.SO_BINDTOIFINDEX, int(index))
	if errors.Is(err, unix.ENOPROTOOPT) {
		// Before Linux 5.0: by name.
		iface, ierr := net.InterfaceByIndex(int(index))
		if ierr != nil {
			return ierr
		}
		err = unix.BindToDevice(fd, iface.Name)
	}
	if errors.Is(err, unix.EPERM) {
		return errors.New("binding a socket to a network needs Linux 5.7 or later")
	}
	return err
}

// Supported reports whether the core can keep its connections outside a
// TUN: whether this process may bind a socket to an interface.
func Supported() error {
	fd, err := unix.Socket(unix.AF_INET, unix.SOCK_DGRAM|unix.SOCK_CLOEXEC, 0)
	if err != nil {
		return err
	}
	defer unix.Close(fd)
	lo, err := net.InterfaceByName("lo")
	if err != nil {
		return err
	}
	return bindToInterface(fd, uint32(lo.Index))
}

// resolvConfs are where the DNS servers are: systemd-resolved's list of
// the servers it uses (the system's resolv.conf names only resolved), and
// the system's.
var resolvConfs = []string{"/run/systemd/resolve/resolv.conf", "/etc/resolv.conf"}

// dnsServers are the system's DNS servers but the TUN's (resolved lists
// it too while the TUN runs), else the IPv4 default route's gateway, port
// 53.
func dnsServers(st *tunState) []netip.AddrPort {
	var servers []netip.Addr
	for _, path := range resolvConfs {
		servers = append(servers, resolvConf(path)...)
	}
	if ports := dnsPorts(servers, st); len(ports) > 0 {
		return ports
	}
	if r, ok := defaultRoute(false, st); ok && r.gateway.IsValid() && !r.gateway.IsUnspecified() {
		return []netip.AddrPort{netip.AddrPortFrom(r.gateway, 53)}
	}
	return nil
}
