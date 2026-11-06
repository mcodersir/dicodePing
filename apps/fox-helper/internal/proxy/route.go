package proxy

import (
	"context"
	"errors"
	"fmt"
	"net"
	"net/netip"
	"strings"
	"sync/atomic"
	"syscall"
	"time"

	"dicodeping/fox/internal/egress"
	"dicodeping/fox/internal/logx"
	"dicodeping/fox/internal/resolver"
	"dicodeping/fox/internal/routing"
)

// ErrBlockedByRule is a connection refused by a routing rule.
var ErrBlockedByRule = errors.New("refused by a routing rule")

// ErrThisMachine is a direct connection from another device to this machine
// itself, which the proxy refuses whatever the rules say (refuseThisMachine).
var ErrThisMachine = fmt.Errorf("%w: the proxy does not connect to this machine itself", ErrBlockedByRule)

// directDialTimeout bounds a direct connection.
const directDialTimeout = 15 * time.Second

// pushDirectTimeout bounds the direct try of Google's push server, and
// pushThroughMozillaFor is how long its connections then go through Mozilla
// without trying directly again.
const (
	pushDirectTimeout     = 5 * time.Second
	pushThroughMozillaFor = 10 * time.Minute
)

// RouteCounts counts connections by route since the proxy started.
type RouteCounts struct {
	Proxy   int64 `json:"proxy"`
	Direct  int64 `json:"direct"`
	Blocked int64 `json:"blocked"`
}

// RoutedOpener opens each tunnel through Mozilla's proxy, directly through
// the local network, or not at all, as its router decides. Without a
// router everything goes through the proxy, and with or without one, an address
// of the local network that no rule blocks goes directly (LocalAddress). The
// router can be replaced while connections are open.
type RoutedOpener struct {
	upstream tunnelOpener
	router   atomic.Pointer[routing.Router]
	// dial connects directly for clients on this machine, dialRemote for
	// clients on other devices; tests replace them.
	dial, dialRemote func(ctx context.Context, network, address string) (net.Conn, error)
	// lookup resolves names for the router's IP rules (routing
	// resolve_domains) through Mozilla; tests replace it.
	lookup routing.LookupFunc
	// exchange answers the DNS a client sends through the proxy, which
	// Mozilla does not carry (DNSPort), with DNS over HTTPS through
	// Mozilla; tests replace it.
	exchange ExchangeFunc
	dnsNoted atomic.Bool
	// pushViaMozillaUntil (Unix nanoseconds) is set when Google's push
	// server could not be reached directly (openPush).
	pushViaMozillaUntil      atomic.Int64
	proxied, direct, blocked atomic.Int64
	meter                    *trafficMeter
	// closed: the engine stopped, and its clients' UDP associations must end,
	// so that they ask the next engine.
	closed atomic.Bool
}

// directDial opens the connections routed directly with the local
// network's own DNS, not dns.servers: they go to the local country's
// sites, whose names its DNS answers best (with the nearest servers), and a
// filtering DNS only hijacks foreign names. While the TUN mode runs, both
// the connection and the DNS go outside the TUN adapter (egress).
// remoteDirectDial does the same for clients on other devices, but never
// connects to this machine itself (refuseThisMachine).
func directDial(ctx context.Context, network, address string) (net.Conn, error) {
	return egress.ClientDialer(0).DialContext(ctx, network, address)
}

func remoteDirectDial(ctx context.Context, network, address string) (net.Conn, error) {
	d := egress.ClientDialer(0)
	d.Control = func(network, address string, c syscall.RawConn) error {
		if err := refuseThisMachine(network, address, c); err != nil {
			return err
		}
		return egress.Control(network, address, c)
	}
	return d.DialContext(ctx, network, address)
}

// refuseThisMachine keeps clients on other devices, when the proxy is
// shared, off this machine's own services (the dashboard among them) and
// off link-local addresses (a cloud server's metadata service,
// 169.254.169.254): a direct route never connects to a loopback,
// unspecified, or link-local address, whatever name led there. It runs on
// the resolved address. A client on this machine reaches those anyway.
func refuseThisMachine(_, address string, _ syscall.RawConn) error {
	host, _, err := net.SplitHostPort(address)
	if err != nil {
		return err
	}
	if ip, err := netip.ParseAddr(host); err == nil {
		if ip = ip.Unmap(); ip.IsLoopback() || ip.IsUnspecified() || ip.IsLinkLocalUnicast() {
			return ErrThisMachine
		}
	}
	return nil
}

// LocalAddress reports whether host is an address of this machine or the local
// network, which Mozilla's proxy cannot reach.
func LocalAddress(host string) bool {
	ip, err := netip.ParseAddr(host)
	if err != nil {
		return false
	}
	ip = ip.Unmap()
	return ip.IsPrivate() || ip.IsLoopback() || ip.IsLinkLocalUnicast()
}

// decide is where a connection to host goes.
func (o *RoutedOpener) decide(host string) routing.Action {
	action := routing.Proxy
	if r := o.router.Load(); r != nil {
		action = r.Decide(context.Background(), host, o.lookup)
	}
	if action == routing.Proxy && LocalAddress(host) {
		return routing.Direct
	}
	return action
}

// remoteClient reports whether a client key (the client's IP, see
// clientAffinityKey) is another device: not loopback. The core's own calls
// carry no key.
func remoteClient(clientKey string) bool {
	if clientKey == "" {
		return false
	}
	ip, err := netip.ParseAddr(clientKey)
	return err != nil || !ip.Unmap().IsLoopback()
}

// NewRoutedOpener routes the tunnels of upstream; Close stops its speed
// sampling.
func NewRoutedOpener(upstream tunnelOpener) *RoutedOpener {
	o := &RoutedOpener{upstream: upstream, dial: directDial, dialRemote: remoteDirectDial, meter: newTrafficMeter()}
	// Names are looked up with DNS over HTTPS inside tunnels through
	// Mozilla: the local network's DNS may be filtered and answer a
	// blocked name with its block page's address (10.10.34.35 in Iran),
	// which IP rules such as geoip:private would then send directly.
	// These tunnels are not counted as client connections.
	names := resolver.NewThrough(func(_ context.Context, _, address string) (net.Conn, error) {
		return upstream.OpenTunnel(address)
	})
	o.lookup = func(ctx context.Context, host string) ([]netip.Addr, error) {
		result, err := names.Lookup(ctx, host)
		return result.Addrs, err
	}
	o.exchange = names.Exchange
	return o
}

// Lookup resolves host the way the router's IP rules see it: through
// Mozilla.
func (o *RoutedOpener) Lookup(ctx context.Context, host string) ([]netip.Addr, error) {
	return o.lookup(ctx, host)
}

// Close stops measuring the speed, and new UDP tunnels.
func (o *RoutedOpener) Close() {
	o.closed.Store(true)
	o.meter.close()
}

// Traffic returns the bytes and speed so far.
func (o *RoutedOpener) Traffic() Traffic { return o.meter.traffic() }

// SetRouter installs r; nil sends everything through the proxy.
func (o *RoutedOpener) SetRouter(r *routing.Router) { o.router.Store(r) }

// Counts returns the connections by route so far.
func (o *RoutedOpener) Counts() RouteCounts {
	return RouteCounts{Proxy: o.proxied.Load(), Direct: o.direct.Load(), Blocked: o.blocked.Load()}
}

func (o *RoutedOpener) OpenTunnel(authority string) (net.Conn, error) {
	return o.OpenTunnelForClient(authority, "")
}

// throughMozilla is authority as it can go through Mozilla, which connects
// to web ports only: git over SSH to GitHub (github.com:22) goes to
// ssh.github.com:443, GitHub's SSH server on the HTTPS port, with the same
// protocol and host keys; Google's push server on its own ports goes to
// the same server's port 443, which speaks the same protocol (pushServer).
func throughMozilla(authority string) string {
	if strings.EqualFold(authority, githubSSH) {
		logx.Debug("GitHub's SSH through port 443 target=%s", logx.Target(authority))
		return "ssh.github.com:443"
	}
	if host, ok := pushServer(authority); ok {
		return net.JoinHostPort(host, "443")
	}
	return authority
}

const githubSSH = "github.com:22"

// pushServer reports whether authority is Google's push server, which
// delivers Android's notifications (Firebase Cloud Messaging): mtalk.google.com
// or a backup altN-mtalk.google.com, on its ports 5228-5230 or 443. It returns
// the host in lower case.
func pushServer(authority string) (string, bool) {
	host, port, err := net.SplitHostPort(authority)
	if err != nil {
		return "", false
	}
	switch port {
	case "443", "5228", "5229", "5230":
	default:
		return "", false
	}
	host = strings.ToLower(strings.TrimSuffix(host, "."))
	if host == "mtalk.google.com" {
		return host, true
	}
	n, ok := strings.CutPrefix(host, "alt")
	if !ok {
		return "", false
	}
	n, ok = strings.CutSuffix(n, "-mtalk.google.com")
	if !ok || n == "" || strings.Trim(n, "0123456789") != "" {
		return "", false
	}
	return host, true
}

// Carried reports whether a connection to host:port can go through
// Mozilla's proxy: one of its ports, GitHub's SSH, or Google's push server
// (throughMozilla).
func Carried(host, port string) bool {
	authority := net.JoinHostPort(host, port)
	if _, ok := pushServer(authority); ok {
		return true
	}
	return PortAllowed(port) || strings.EqualFold(authority, githubSSH)
}

// openPush connects to Google's push server directly: it keeps one long
// connection open for the notifications of every app, which then neither
// waits for nor breaks with the connection to Mozilla. When it cannot be
// reached directly within pushDirectTimeout, it and the next ones go
// through Mozilla on port 443 for pushThroughMozillaFor. ok is false when
// the connection is to go through Mozilla.
func (o *RoutedOpener) openPush(authority, clientKey string) (conn net.Conn, ok bool) {
	if time.Now().UnixNano() < o.pushViaMozillaUntil.Load() {
		return nil, false
	}
	dial := o.dial
	if remoteClient(clientKey) && o.dialRemote != nil {
		dial = o.dialRemote
	}
	ctx, cancel := context.WithTimeout(context.Background(), pushDirectTimeout)
	defer cancel()
	conn, err := dial(ctx, "tcp", authority)
	if err != nil {
		o.pushViaMozillaUntil.Store(time.Now().Add(pushThroughMozillaFor).UnixNano())
		logx.Info("Google's push server could not be reached directly; notifications go through Mozilla for %s target=%s err=%s", pushThroughMozillaFor, logx.Target(authority), logx.Err(err))
		return nil, false
	}
	o.direct.Add(1)
	logx.Debug("Google's push server directly target=%s", logx.Target(authority))
	return countRouted(conn, &o.meter.directUp, &o.meter.directDown, RouteDirect), true
}

// OpenTunnelForClient keeps the client affinity of the upstream pool.
func (o *RoutedOpener) OpenTunnelForClient(authority, clientKey string) (net.Conn, error) {
	if host, _, err := net.SplitHostPort(authority); err == nil {
		switch o.decide(host) {
		case routing.Direct:
			o.direct.Add(1)
			logx.Debug("route direct target=%s", logx.Target(authority))
			ctx, cancel := context.WithTimeout(context.Background(), directDialTimeout)
			defer cancel()
			dial := o.dial
			if remoteClient(clientKey) && o.dialRemote != nil {
				dial = o.dialRemote
			}
			conn, err := dial(ctx, "tcp", authority)
			if errors.Is(err, ErrThisMachine) {
				o.direct.Add(-1)
				o.blocked.Add(1)
				logx.Debug("route blocked: this machine itself target=%s", logx.Target(authority))
			}
			if err != nil {
				return nil, err
			}
			return countRouted(conn, &o.meter.directUp, &o.meter.directDown, RouteDirect), nil
		case routing.Block:
			o.blocked.Add(1)
			logx.Debug("route blocked target=%s", logx.Target(authority))
			return nil, ErrBlockedByRule
		}
	}
	if _, push := pushServer(authority); push {
		if conn, ok := o.openPush(authority, clientKey); ok {
			return conn, nil
		}
	}
	o.proxied.Add(1)
	if _, port, err := net.SplitHostPort(authority); err == nil && port == DNSPort && o.exchange != nil {
		if o.dnsNoted.CompareAndSwap(false, true) {
			logx.Info("DNS a client sends through the proxy (port 53, which Mozilla does not connect to) is answered here, with DNS over HTTPS through Mozilla")
		}
		logx.Debug("DNS through the proxy answered here target=%s", logx.Target(authority))
		client, server := net.Pipe()
		go serveDNS(server, o.exchange)
		return countRouted(client, &o.meter.up, &o.meter.down, RouteVPN), nil
	}
	authority = throughMozilla(authority)
	var conn net.Conn
	var err error
	if affinity, ok := o.upstream.(clientAffinityTunnelOpener); ok && clientKey != "" {
		conn, err = affinity.OpenTunnelForClient(authority, clientKey)
	} else {
		conn, err = o.upstream.OpenTunnel(authority)
	}
	if err != nil {
		return nil, err
	}
	return countRouted(conn, &o.meter.up, &o.meter.down, RouteVPN), nil
}
