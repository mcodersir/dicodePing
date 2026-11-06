// Package egress keeps the core's own connections out of the TUN adapter of
// the desktop TUN mode. While a TUN runs (SetTun), the adapter holds the
// default routes, so a connection the core opens itself (to Mozilla, the
// account and server-list APIs, DNS over HTTPS, a destination routed
// directly) would go into the TUN, to the TUN service, and back to the
// core's own proxy. Every outgoing socket the core opens is therefore bound
// to the interface that has the default route besides the TUN (Control),
// chosen again for each socket, so a change of network (Wi-Fi to Ethernet)
// is followed; and the names the system's resolver would answer (with the
// TUN's fake addresses) are asked of that network's own DNS servers
// instead. Without a TUN nothing changes.
package egress

import (
	"context"
	"errors"
	"net"
	"net/netip"
	"strings"
	"sync"
	"sync/atomic"
	"syscall"
	"time"
)

// tunState is the running TUN adapter.
type tunState struct {
	index uint32
	luid  uint64
}

var current atomic.Pointer[tunState]

// SetTun binds the core's sockets outside the TUN adapter with this
// interface index and LUID, from now on.
func SetTun(index uint32, luid uint64) {
	current.Store(&tunState{index: index, luid: luid})
	forget()
}

// ClearTun ends the binding.
func ClearTun() {
	current.Store(nil)
	forget()
}

// Tun is the TUN adapter while one runs.
func Tun() (index uint32, luid uint64, ok bool) {
	st := current.Load()
	if st == nil {
		return 0, 0, false
	}
	return st.index, st.luid, true
}

// ErrNoNetwork means no interface but the TUN has a default route: a
// connection now would go into the TUN, so it is not made.
var ErrNoNetwork = errors.New("no network outside the TUN adapter")

// Control binds a socket being connected to address outside the TUN while
// one runs (net.Dialer.Control). A destination whose best route is another
// network than the TUN and the default one (a second LAN, WSL's or a
// virtual machine's) keeps that route (keepRoute).
// ExternalControl lets DicodePing bind desktop sockets to the physical uplink.
// Configured once before any connections are opened.
var ExternalControl func(string, string, syscall.RawConn) error

func Control(network, address string, c syscall.RawConn) error {
	if ExternalControl != nil {
		if err := ExternalControl(network, address, c); err != nil {
			return err
		}
	}
	st := current.Load()
	if st == nil {
		return nil
	}
	var dst netip.Addr
	if ap, err := netip.ParseAddrPort(address); err == nil {
		dst = ap.Addr().Unmap()
	}
	if dst.IsLoopback() || local(dst) {
		return nil
	}
	v6 := dst.Is6() || (!dst.IsValid() && network[len(network)-1] == '6')
	index, ok := physical(v6, st)
	if !ok {
		return ErrNoNetwork
	}
	if dst.IsValid() && !dst.IsUnspecified() {
		if best, ok := bestInterface(dst); ok && best != st.index && best != index {
			return keepRoute(c, v6, best)
		}
	}
	return bind(c, v6, index)
}

// localAddrs keeps this computer's addresses a moment.
var localAddrs struct {
	mu    sync.Mutex
	at    time.Time
	addrs map[netip.Addr]bool
}

// local reports whether addr is one of this computer's own addresses (a
// DNS server can be one: WSL's is on loopback), which a connection reaches
// without leaving the computer, whatever it is bound to.
func local(addr netip.Addr) bool {
	localAddrs.mu.Lock()
	defer localAddrs.mu.Unlock()
	if time.Since(localAddrs.at) > time.Second {
		localAddrs.addrs = map[netip.Addr]bool{}
		if addrs, err := net.InterfaceAddrs(); err == nil {
			for _, a := range addrs {
				if p, err := netip.ParsePrefix(a.String()); err == nil {
					localAddrs.addrs[p.Addr().Unmap()] = true
				}
			}
		}
		localAddrs.at = time.Now()
	}
	return localAddrs.addrs[addr.WithZone("")]
}

// Dialer is a net.Dialer for this program's own connections: from outside
// the TUN while one runs, resolving names with the physical network's DNS,
// and noted by address (OwnDial). Make one for each connection, since a
// TUN may start or stop between them.
func Dialer(timeout time.Duration) *net.Dialer {
	d := ClientDialer(timeout)
	d.Control = func(network, address string, c syscall.RawConn) error {
		noteOwn(address)
		return Control(network, address, c)
	}
	return d
}

// ClientDialer is Dialer for a client's connection (a direct route), which
// is not noted as this program's own.
func ClientDialer(timeout time.Duration) *net.Dialer {
	d := &net.Dialer{Timeout: timeout, Control: Control}
	if current.Load() != nil {
		d.Resolver = physicalResolver
	}
	return d
}

// ownWindow is how long the address of one of this program's own
// connections is remembered.
const ownWindow = 10 * time.Second

// ownDials are the addresses this program itself connected to lately, by
// address and port, so that one coming back into its proxy as a client's
// connection shows a loop: something (PassWall2's Localhost Proxy, another
// VPN program's TUN) sends this program's own traffic into its proxy, and
// nothing connects.
var ownDials struct {
	mu sync.Mutex
	at map[string]time.Time
}

// ownNow is the clock of ownDials; tests replace it.
var ownNow = time.Now

// maxOwnDials bounds ownDials.
const maxOwnDials = 256

func noteOwn(address string) {
	key := ownKey(address)
	if key == "" {
		return
	}
	now := ownNow()
	ownDials.mu.Lock()
	defer ownDials.mu.Unlock()
	if ownDials.at == nil {
		ownDials.at = map[string]time.Time{}
	}
	if len(ownDials.at) >= maxOwnDials {
		for k, at := range ownDials.at {
			if now.Sub(at) > ownWindow {
				delete(ownDials.at, k)
			}
		}
		if len(ownDials.at) >= maxOwnDials {
			return
		}
	}
	ownDials.at[key] = now
}

// OwnDial reports whether target (host:port) is an address this program
// itself connected to in the last few seconds: a client's connection to it
// may be this program's own, sent back into its proxy.
func OwnDial(target string) bool {
	key := ownKey(target)
	if key == "" {
		return false
	}
	ownDials.mu.Lock()
	defer ownDials.mu.Unlock()
	at, ok := ownDials.at[key]
	return ok && ownNow().Sub(at) <= ownWindow
}

// ownKey writes an address one way: an IPv4 address mapped into IPv6 as
// IPv4, without a zone; a name in lower case. Loopback gives "": it never
// leaves this computer, so it never loops.
func ownKey(address string) string {
	if ap, err := netip.ParseAddrPort(address); err == nil {
		if ap.Addr().Unmap().IsLoopback() {
			return ""
		}
		return netip.AddrPortFrom(ap.Addr().Unmap().WithZone(""), ap.Port()).String()
	}
	if host, _, err := net.SplitHostPort(address); err == nil && strings.EqualFold(host, "localhost") {
		return ""
	}
	return strings.ToLower(address)
}

// DialContext connects with Dialer(0).
func DialContext(ctx context.Context, network, address string) (net.Conn, error) {
	return Dialer(0).DialContext(ctx, network, address)
}

// LookupNetIP resolves host as the system's resolver does; while a TUN
// runs, by asking the physical network's DNS servers.
func LookupNetIP(ctx context.Context, host string) ([]netip.Addr, error) {
	r := net.DefaultResolver
	if current.Load() != nil {
		r = physicalResolver
	}
	return r.LookupNetIP(ctx, "ip", host)
}

// ListenUDP opens an unconnected UDP socket for talking to dst (QUIC), of
// its family, bound outside the TUN while one runs.
func ListenUDP(dst netip.Addr) (*net.UDPConn, error) {
	dst = dst.Unmap()
	network := "udp4"
	if dst.Is6() {
		network = "udp6"
	}
	lc := net.ListenConfig{Control: func(network, _ string, c syscall.RawConn) error {
		return Control(network, netip.AddrPortFrom(dst, 0).String(), c)
	}}
	pc, err := lc.ListenPacket(context.Background(), network, ":0")
	if err != nil {
		return nil, err
	}
	return pc.(*net.UDPConn), nil
}

// physicalResolver is Go's resolver asking the physical network's DNS
// servers (also for TCP), over sockets bound outside the TUN; it reads the
// hosts file like the system's.
var physicalResolver = &net.Resolver{PreferGo: true, Dial: dialDNS}

// dnsTurn spreads Go's resolver's attempts over the servers.
var dnsTurn atomic.Uint32

func dialDNS(ctx context.Context, network, _ string) (net.Conn, error) {
	st := current.Load()
	if st == nil {
		return nil, errors.New("no TUN runs")
	}
	servers := dnsServers(st)
	if len(servers) == 0 {
		return nil, errors.New("the network outside the TUN adapter has no DNS servers")
	}
	server := servers[int(dnsTurn.Add(1))%len(servers)]
	d := net.Dialer{Control: Control}
	return d.DialContext(ctx, network, server.String())
}
