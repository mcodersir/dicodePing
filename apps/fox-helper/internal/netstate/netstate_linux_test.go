//go:build linux

package netstate

import (
	"strings"
	"testing"
)

func TestLinuxDefaultRoutes(t *testing.T) {
	for line, want := range map[string]bool{
		"eth0	00000000	0102A8C0	0003	0	0	100	00000000	0	0	0": true,
		"eth0	00000000	0102A8C0	0002	0	0	100	00000000	0	0	0": false, // not up
		"eth0	0002A8C0	00000000	0001	0	0	100	00FFFFFF	0	0	0": false, // not default
		"lo	00000000	00000000	0001	0	0	0	00000000	0	0	0":     false,
	} {
		if got := parseRoute4(strings.Fields(line), ""); got != want {
			t.Errorf("parseRoute4(%q) = %t", line, got)
		}
	}
	zero := strings.Repeat("0", 32)
	for line, want := range map[string]bool{
		zero + " 00 " + zero + " 00 fe800000000000000000000000000001 00000400 00000001 00000000 00000003 wlan0":      true,
		zero + " 00 " + zero + " 00 " + zero + " ffffffff 00000001 00000000 00200200 lo":                             false,
		"fe800000000000000000000000000000 40 " + zero + " 00 " + zero + " 00000100 00000001 00000000 00000001 wlan0": false,
	} {
		if got := parseRoute6(strings.Fields(line), ""); got != want {
			t.Errorf("parseRoute6(%q) = %t", line, got)
		}
	}
}

// The TUN mode's adapter has an IPv6 default route of its own table, which
// /proc lists with the system's; it is no network.
func TestTheTunsDefaultRouteIsNoNetwork(t *testing.T) {
	zero := strings.Repeat("0", 32)
	tun := strings.Fields(zero + " 00 " + zero + " 00 " + zero + " 00000400 00000001 00000000 00000001 arman-vpn")
	if !parseRoute6(tun, "") || parseRoute6(tun, "arman-vpn") {
		t.Fatal("the TUN's default route is not told apart")
	}
	if parseRoute4(strings.Fields("arman-vpn	00000000	00000000	0001	0	0	0	00000000	0	0	0"), "arman-vpn") {
		t.Fatal("the TUN's IPv4 default route counts")
	}
}
