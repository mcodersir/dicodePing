package egress

import (
	"net"
	"net/netip"
	"os"
	"os/exec"
	"strings"
	"sync"
	"sync/atomic"
	"syscall"
	"time"

	"golang.org/x/net/route"
	"golang.org/x/sys/unix"
)

// On macOS the TUN's routes are more specific than the default route,
// which stays: a socket bound to an interface (IP_BOUND_IF) uses that
// interface's routes only.

// defaultInterface is the interface of the primary default route (macOS
// scopes the others to their interfaces) when it is up and is not the TUN
// adapter.
func defaultInterface(v6 bool, st *tunState) (uint32, bool) {
	index, _, ok := defaultRoute(v6, st)
	return index, ok
}

func defaultRoute(v6 bool, st *tunState) (uint32, netip.Addr, bool) {
	family := unix.AF_INET
	if v6 {
		family = unix.AF_INET6
	}
	rib, err := route.FetchRIB(family, route.RIBTypeRoute, 0)
	if err != nil {
		return 0, netip.Addr{}, false
	}
	msgs, err := route.ParseRIB(route.RIBTypeRoute, rib)
	if err != nil {
		return 0, netip.Addr{}, false
	}
	for _, m := range msgs {
		rm, ok := m.(*route.RouteMessage)
		if !ok || rm.Flags&unix.RTF_UP == 0 || rm.Flags&(unix.RTF_IFSCOPE|unix.RTF_HOST|unix.RTF_REJECT|unix.RTF_BLACKHOLE) != 0 {
			continue
		}
		if !isDefault(rm.Addrs) || uint32(rm.Index) == st.index || !interfaceUp(rm.Index) {
			continue
		}
		return uint32(rm.Index), addrOf(rm.Addrs, unix.RTAX_GATEWAY), true
	}
	return 0, netip.Addr{}, false
}

// isDefault reports whether a route's destination is the whole family.
func isDefault(addrs []route.Addr) bool {
	dst := addrOf(addrs, unix.RTAX_DST)
	if !dst.IsValid() || !dst.IsUnspecified() {
		return false
	}
	mask := addrOf(addrs, unix.RTAX_NETMASK)
	return !mask.IsValid() || mask.IsUnspecified()
}

func addrOf(addrs []route.Addr, i int) netip.Addr {
	if i >= len(addrs) {
		return netip.Addr{}
	}
	switch a := addrs[i].(type) {
	case *route.Inet4Addr:
		return netip.AddrFrom4(a.IP)
	case *route.Inet6Addr:
		return netip.AddrFrom16(a.IP)
	}
	return netip.Addr{}
}

var routeSeq atomic.Int32

// bestInterface is the interface the system sends to dst through: its
// answer to a route lookup (RTM_GET).
func bestInterface(dst netip.Addr) (uint32, bool) {
	fd, err := unix.Socket(unix.AF_ROUTE, unix.SOCK_RAW, unix.AF_UNSPEC)
	if err != nil {
		return 0, false
	}
	defer unix.Close(fd)
	_ = unix.SetsockoptTimeval(fd, unix.SOL_SOCKET, unix.SO_RCVTIMEO, &unix.Timeval{Sec: 1})
	var a route.Addr = &route.Inet4Addr{IP: dst.As4()}
	if dst.Is6() {
		a = &route.Inet6Addr{IP: dst.As16()}
	}
	seq := int(routeSeq.Add(1))
	pid := uintptr(os.Getpid())
	// An empty link address asks for the route's interface (RTA_IFP), as
	// route(8) does.
	req := route.RouteMessage{Version: unix.RTM_VERSION, Type: unix.RTM_GET, Flags: unix.RTF_UP | unix.RTF_HOST, ID: pid, Seq: seq,
		Addrs: []route.Addr{unix.RTAX_DST: a, unix.RTAX_IFP: &route.LinkAddr{}}}
	b, err := req.Marshal()
	if err != nil {
		return 0, false
	}
	if _, err := unix.Write(fd, b); err != nil {
		return 0, false
	}
	buf := make([]byte, 4096)
	// The socket also gets every other routing message; ours is the one
	// with our process and sequence number.
	for range 32 {
		n, err := unix.Read(fd, buf)
		if err != nil {
			return 0, false
		}
		msgs, err := route.ParseRIB(route.RIBTypeRoute, buf[:n])
		if err != nil {
			continue
		}
		for _, m := range msgs {
			if rm, ok := m.(*route.RouteMessage); ok && rm.ID == pid && rm.Seq == seq {
				if rm.Err != nil {
					return 0, false
				}
				index := rm.Index
				if len(rm.Addrs) > unix.RTAX_IFP {
					if l, ok := rm.Addrs[unix.RTAX_IFP].(*route.LinkAddr); ok && l.Index > 0 {
						index = l.Index
					}
				}
				return uint32(index), index > 0
			}
		}
	}
	return 0, false
}

// bind pins the socket to interface index (IP_BOUND_IF, IPV6_BOUND_IF).
func bind(c syscall.RawConn, v6 bool, index uint32) error {
	var opErr error
	err := c.Control(func(fd uintptr) {
		if v6 {
			opErr = unix.SetsockoptInt(int(fd), unix.IPPROTO_IPV6, unix.IPV6_BOUND_IF, int(index))
			return
		}
		opErr = unix.SetsockoptInt(int(fd), unix.IPPROTO_IP, unix.IP_BOUND_IF, int(index))
	})
	if err != nil {
		return err
	}
	return opErr
}

// Supported: the core's sockets can always be bound outside a TUN here.
func Supported() error { return nil }

// dhcpCache keeps an interface's DHCP DNS servers a while: asking runs
// ipconfig.
var dhcpCache struct {
	mu      sync.Mutex
	iface   string
	at      time.Time
	servers []netip.Addr
}

const dhcpFresh = 30 * time.Second

// dnsServers are the DNS servers the network gave by DHCP on the IPv4
// default interface outside the TUN, else its gateway, port 53: while the
// TUN runs, the TUN service has made the TUN's the system's.
func dnsServers(st *tunState) []netip.AddrPort {
	index, gateway, ok := defaultRoute(false, st)
	if !ok {
		return nil
	}
	iface, err := net.InterfaceByIndex(int(index))
	if err != nil {
		return nil
	}
	if ports := dnsPorts(dhcpDNS(iface.Name), st); len(ports) > 0 {
		return ports
	}
	if gateway.IsValid() && !gateway.IsUnspecified() {
		return []netip.AddrPort{netip.AddrPortFrom(gateway, 53)}
	}
	return nil
}

func dhcpDNS(iface string) []netip.Addr {
	dhcpCache.mu.Lock()
	defer dhcpCache.mu.Unlock()
	if dhcpCache.iface == iface && time.Since(dhcpCache.at) < dhcpFresh {
		return dhcpCache.servers
	}
	out, err := exec.Command("/usr/sbin/ipconfig", "getpacket", iface).Output()
	var servers []netip.Addr
	if err == nil {
		servers = dhcpServers(string(out))
	}
	dhcpCache.iface, dhcpCache.at, dhcpCache.servers = iface, time.Now(), servers
	return servers
}

// dhcpServers reads the DNS servers from ipconfig's DHCP packet:
// "domain_name_server (ip_mult): {192.168.1.1, 192.168.1.2}".
func dhcpServers(packet string) []netip.Addr {
	var servers []netip.Addr
	for _, line := range strings.Split(packet, "\n") {
		name, value, ok := strings.Cut(line, ":")
		if !ok || !strings.HasPrefix(strings.TrimSpace(name), "domain_name_server") {
			continue
		}
		value = strings.Trim(strings.TrimSpace(value), "{}")
		for _, s := range strings.Split(value, ",") {
			if a, err := netip.ParseAddr(strings.TrimSpace(s)); err == nil {
				servers = append(servers, a)
			}
		}
	}
	return servers
}
