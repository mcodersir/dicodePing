//go:build !windows && !darwin && (!linux || android)

package egress

import (
	"errors"
	"net/netip"
	"syscall"
)

// The desktop TUN mode runs on Windows, Linux, and macOS; SetTun is never
// called here (Android's VPN keeps the core's sockets out of it itself).

var errNotHere = errors.New("the TUN mode is not available on this system")

func forget() {}

func physical(bool, *tunState) (uint32, bool) { return 0, false }

func bestInterface(netip.Addr) (uint32, bool) { return 0, false }

func bind(syscall.RawConn, bool, uint32) error { return errNotHere }

func keepRoute(syscall.RawConn, bool, uint32) error { return errNotHere }

func dnsServers(*tunState) []netip.AddrPort { return nil }

// Supported: not here.
func Supported() error { return errNotHere }
