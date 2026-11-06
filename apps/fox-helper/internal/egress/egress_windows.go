package egress

import (
	"encoding/binary"
	"errors"
	"net/netip"
	"syscall"
	"unsafe"

	"golang.org/x/sys/windows"
)

// Socket options that pin a socket's outgoing interface (ws2ipdef.h).
const (
	ipUnicastIf   = 31
	ipv6UnicastIf = 31
)

// bind pins the socket to interface index. For IPv4 the index is passed
// in network byte order, as an address in 0.0.0.0/8 would be.
func bind(c syscall.RawConn, v6 bool, index uint32) error {
	var opErr error
	err := c.Control(func(fd uintptr) {
		if v6 {
			opErr = windows.SetsockoptInt(windows.Handle(fd), windows.IPPROTO_IPV6, ipv6UnicastIf, int(index))
			return
		}
		var b [4]byte
		binary.BigEndian.PutUint32(b[:], index)
		opErr = windows.SetsockoptInt(windows.Handle(fd), windows.IPPROTO_IP, ipUnicastIf, int(binary.NativeEndian.Uint32(b[:])))
	})
	if err != nil {
		return err
	}
	return opErr
}

// bestInterface is the interface Windows would send to dst through.
func bestInterface(dst netip.Addr) (uint32, bool) {
	var sa windows.Sockaddr
	if dst.Is4() {
		sa = &windows.SockaddrInet4{Addr: dst.As4()}
	} else {
		sa = &windows.SockaddrInet6{Addr: dst.As16()}
	}
	var index uint32
	if err := windows.GetBestInterfaceEx(sa, &index); err != nil {
		return 0, false
	}
	return index, true
}

// keepRoute: Windows sends a socket left unbound along its best route.
func keepRoute(syscall.RawConn, bool, uint32) error { return nil }

// Supported: the core's sockets can always be bound outside a TUN here.
func Supported() error { return nil }

// defaultInterface is the interface of the default route with the lowest
// metric (the route's and its interface's) whose interface is up and is
// not the TUN adapter.
func defaultInterface(v6 bool, st *tunState) (uint32, bool) {
	family := uint16(windows.AF_INET)
	if v6 {
		family = windows.AF_INET6
	}
	tun := st.luid
	var table *windows.MibIpForwardTable2
	if err := windows.GetIpForwardTable2(family, &table); err != nil {
		return 0, false
	}
	defer windows.FreeMibTable(unsafe.Pointer(table))
	var best uint32
	bestMetric := ^uint32(0)
	for _, row := range table.Rows() {
		if row.DestinationPrefix.PrefixLength != 0 || row.InterfaceLuid == tun {
			continue
		}
		ifRow := windows.MibIfRow2{InterfaceLuid: row.InterfaceLuid}
		if windows.GetIfEntry2Ex(windows.MibIfEntryNormal, &ifRow) != nil ||
			ifRow.OperStatus != windows.IfOperStatusUp || ifRow.Type == windows.IF_TYPE_SOFTWARE_LOOPBACK {
			continue
		}
		ipRow := windows.MibIpInterfaceRow{Family: family, InterfaceLuid: row.InterfaceLuid}
		if windows.GetIpInterfaceEntry(&ipRow) != nil || ipRow.Connected == 0 {
			continue
		}
		if metric := row.Metric + ipRow.Metric; metric < bestMetric {
			best, bestMetric = row.InterfaceIndex, metric
		}
	}
	return best, bestMetric != ^uint32(0)
}

// dnsServers are the DNS servers of the IPv4 default interface outside
// the TUN (else the IPv6 one), port 53; not Windows' unanswered fec0::
// placeholders.
func dnsServers(st *tunState) []netip.AddrPort {
	index, ok := physical(false, st)
	if !ok {
		if index, ok = physical(true, st); !ok {
			return nil
		}
	}
	adapters, err := adapterAddresses()
	if err != nil {
		return nil
	}
	var v4, v6 []netip.AddrPort
	for a := adapters; a != nil; a = a.Next {
		if a.IfIndex != index && a.Ipv6IfIndex != index {
			continue
		}
		for d := a.FirstDnsServerAddress; d != nil; d = d.Next {
			ip, ok := netip.AddrFromSlice(d.Address.IP())
			if !ok {
				continue
			}
			ip = ip.Unmap()
			if ip.Is4() {
				v4 = append(v4, netip.AddrPortFrom(ip, 53))
			} else if !netip.MustParsePrefix("fec0::/10").Contains(ip) {
				v6 = append(v6, netip.AddrPortFrom(ip.WithZone(""), 53))
			}
		}
	}
	return append(v4, v6...)
}

func adapterAddresses() (*windows.IpAdapterAddresses, error) {
	const flags = windows.GAA_FLAG_SKIP_ANYCAST | windows.GAA_FLAG_SKIP_MULTICAST | windows.GAA_FLAG_SKIP_FRIENDLY_NAME
	size := uint32(16 << 10)
	for range 3 {
		buf := make([]byte, size)
		first := (*windows.IpAdapterAddresses)(unsafe.Pointer(&buf[0]))
		err := windows.GetAdaptersAddresses(windows.AF_UNSPEC, flags, 0, first, &size)
		if errors.Is(err, windows.ERROR_BUFFER_OVERFLOW) {
			continue
		}
		if err != nil {
			return nil, err
		}
		return first, nil
	}
	return nil, windows.ERROR_BUFFER_OVERFLOW
}
