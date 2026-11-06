//go:build darwin || (linux && !android)

package egress

import (
	"net"
	"net/netip"
	"os"
	"strings"
	"syscall"
)

// keepRoute binds a socket to the network its destination's best route
// uses: on Linux an unbound socket would still follow the TUN's rules
// (all DNS goes into the TUN), so the route is kept by binding to it.
func keepRoute(c syscall.RawConn, v6 bool, index uint32) error {
	return bind(c, v6, index)
}

// interfaceUp reports whether interface index is up and has a link.
func interfaceUp(index int) bool {
	iface, err := net.InterfaceByIndex(index)
	return err == nil && iface.Flags&net.FlagUp != 0 && iface.Flags&net.FlagRunning != 0
}

// resolvConf lists the nameservers of a resolv.conf file.
func resolvConf(path string) []netip.Addr {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil
	}
	var servers []netip.Addr
	for _, line := range strings.Split(string(data), "\n") {
		f := strings.Fields(line)
		if len(f) >= 2 && f[0] == "nameserver" {
			if a, err := netip.ParseAddr(f[1]); err == nil {
				servers = append(servers, a.Unmap())
			}
		}
	}
	return servers
}

// dnsPorts makes servers DNS addresses: IPv4 first, without duplicates or
// the addresses reached through the TUN (its own DNS server) or on this
// computer.
func dnsPorts(servers []netip.Addr, st *tunState) []netip.AddrPort {
	seen := map[netip.Addr]bool{}
	var v4, v6 []netip.AddrPort
	for _, a := range servers {
		if seen[a] || !a.IsValid() || a.IsLoopback() || a.IsUnspecified() {
			continue
		}
		seen[a] = true
		if best, ok := bestInterface(a); ok && best == st.index {
			continue
		}
		if a.Is4() {
			v4 = append(v4, netip.AddrPortFrom(a, 53))
		} else {
			v6 = append(v6, netip.AddrPortFrom(a, 53))
		}
	}
	return append(v4, v6...)
}
