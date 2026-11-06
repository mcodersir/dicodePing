//go:build windows

package netstate

import (
	"errors"
	"slices"
	"strings"
	"unsafe"

	"golang.org/x/sys/windows"

	"dicodeping/fox/internal/egress"
)

// connected looks for an adapter that is up and has a default gateway.
// Adapters without one, such as Hyper-V's vEthernet for WSL and Docker,
// stay up while Wi-Fi and Ethernet are disconnected and do not count.
func connected() bool {
	list, err := adapters()
	if err != nil {
		return true
	}
	for _, a := range list {
		if a.up && a.gateway && !a.loopback {
			return true
		}
	}
	return false
}

// current names the connected networks: each adapter that is up and has a
// default gateway, with its addresses and gateways.
func current() (string, bool) {
	list, err := adapters()
	if err != nil {
		return "", false
	}
	var parts []string
	for _, a := range list {
		if a.up && a.gateway && !a.loopback {
			parts = append(parts, a.name+"="+a.addresses)
		}
	}
	slices.Sort(parts)
	return strings.Join(parts, ";"), true
}

type adapter struct {
	name                  string
	up, gateway, loopback bool
	// addresses are its own and its gateways' addresses.
	addresses string
}

func adapters() ([]adapter, error) {
	const flags = windows.GAA_FLAG_INCLUDE_GATEWAYS | windows.GAA_FLAG_SKIP_ANYCAST | windows.GAA_FLAG_SKIP_MULTICAST | windows.GAA_FLAG_SKIP_DNS_SERVER
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
		_, tun, tunRuns := egress.Tun()
		var list []adapter
		for a := first; a != nil; a = a.Next {
			if tunRuns && a.Luid == tun {
				// The TUN mode's adapter has the default routes but is no
				// network of its own.
				continue
			}
			var addrs []string
			for u := a.FirstUnicastAddress; u != nil; u = u.Next {
				addrs = append(addrs, u.Address.IP().String())
			}
			for g := a.FirstGatewayAddress; g != nil; g = g.Next {
				addrs = append(addrs, "gw "+g.Address.IP().String())
			}
			list = append(list, adapter{
				name:      windows.UTF16PtrToString(a.FriendlyName),
				up:        a.OperStatus == windows.IfOperStatusUp,
				gateway:   a.FirstGatewayAddress != nil,
				loopback:  a.IfType == windows.IF_TYPE_SOFTWARE_LOOPBACK,
				addresses: strings.Join(addrs, ","),
			})
		}
		return list, nil
	}
	return nil, windows.ERROR_BUFFER_OVERFLOW
}
