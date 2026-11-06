package proxy

import (
	"context"
	"errors"
	"fmt"
	"net"
	"net/http"
	"net/url"
	"strconv"
	"sync"
	"sync/atomic"
	"time"

	"dicodeping/fox/internal/logx"
	"dicodeping/fox/internal/routing"
)

// UDP through Mozilla: a UDPTunnel carries one client socket's packets to one
// destination and back, over CONNECT-UDP (udp_h2.go). The Controller opens
// them on HTTP/2 connections of their own; RoutedOpener applies the routing
// rules and the ports; SOCKSServer serves them to clients (socks_udp.go).

// UDPTunnel is packets to one destination and its replies.
type UDPTunnel interface {
	// ReadPacket returns the next packet from the destination; an error ends
	// the tunnel.
	ReadPacket(p []byte) (int, error)
	// WritePacket sends p, which it does not keep. It does not wait; a packet
	// that cannot go now is dropped. An error ends the tunnel.
	WritePacket(p []byte) error
	Close() error
}

// udpTunnelOpener opens UDP tunnels to an authority (host:port) for the
// client with clientKey ("" for the core's own).
type udpTunnelOpener interface {
	OpenUDP(authority, clientKey string) (UDPTunnel, error)
}

// ErrUDPPort is UDP to a port Mozilla's proxy refuses, refused here without
// asking it.
var ErrUDPPort = errors.New("Mozilla's proxy does not carry UDP to this port")

// PortRange is a range of ports, both ends included.
type PortRange struct{ From, To uint16 }

// udpPorts are the UDP destination ports Mozilla's proxy connects to (measured
// 2026-10-30 through the tunnel; others answer 502 with Proxy-Status
// destination_ip_prohibited: 53, 123, 500, 1194, 3479-3481, 4500, 5349, 8000,
// 8801, 10000, 19132, 19302, 27015, 1024-49151, 65535).
var udpPorts = []PortRange{
	{80, 80}, {443, 443}, {3478, 3478}, {8080, 8080}, {8443, 8443}, {49152, 65534},
}

// UDPPorts lists the UDP ports Mozilla's proxy carries.
func UDPPorts() []PortRange { return append([]PortRange(nil), udpPorts...) }

// UDPPortAllowed reports whether Mozilla's proxy carries UDP to port.
func UDPPortAllowed(port string) bool {
	n, err := strconv.ParseUint(port, 10, 16)
	if err != nil {
		return false
	}
	for _, r := range udpPorts {
		if uint16(n) >= r.From && uint16(n) <= r.To {
			return true
		}
	}
	return false
}

const (
	// udpOpenRetries is how many times a failed open is tried again.
	udpOpenRetries = 2
	// udpMaxConns bounds the UDP connections to the proxy.
	udpMaxConns = 8
	// udpSocketErrorPause spaces the reads of a socket reporting errors.
	udpSocketErrorPause = 10 * time.Millisecond
)

var (
	// errUDPBusy is every UDP connection's streams in use.
	errUDPBusy = errors.New("every upstream UDP stream is in use")
	// errUDPEngineStopped ends a client's association: TCP tunnels end with
	// their connections, but an association would otherwise keep asking the
	// stopped engine for as long as its client sends.
	errUDPEngineStopped = errors.New("the proxy engine stopped")
)

// udpUpstream keeps the controller's UDP connections, to one server.
type udpUpstream struct {
	// dialMu makes one dial at a time: those waiting then use its connection.
	dialMu sync.Mutex
	mu     sync.Mutex
	conns  []*udpH2Conn
	server string
	// generation changes with reset, so that a dial begun before it is not
	// kept.
	generation int
	closed     bool
	dial       func(*url.URL, time.Duration) (*udpH2Conn, error)
}

// usable returns a connection to server that takes new streams, forgetting
// ended ones and all those to another server.
func (u *udpUpstream) usable(server string) (*udpH2Conn, error) {
	u.mu.Lock()
	defer u.mu.Unlock()
	if u.closed {
		return nil, ErrNoUsableSession
	}
	if u.server != server {
		u.dropLocked()
		u.server = server
	}
	kept := u.conns[:0]
	var found *udpH2Conn
	for _, c := range u.conns {
		if c.ended() {
			continue
		}
		kept = append(kept, c)
		if found == nil && c.usable() {
			found = c
		}
	}
	u.conns = kept
	return found, nil
}

func (u *udpUpstream) dropLocked() {
	u.generation++
	for _, c := range u.conns {
		c.fail(errUDPConnClosed)
	}
	u.conns = nil
}

// conn returns a connection to target that takes new streams, dialing one
// when none does.
func (u *udpUpstream) conn(target *url.URL, timeout time.Duration) (*udpH2Conn, error) {
	if c, err := u.usable(target.Host); c != nil || err != nil {
		return c, err
	}
	u.dialMu.Lock()
	defer u.dialMu.Unlock()
	if c, err := u.usable(target.Host); c != nil || err != nil {
		return c, err
	}
	u.mu.Lock()
	full := len(u.conns) >= udpMaxConns
	generation := u.generation
	u.mu.Unlock()
	if full {
		return nil, errUDPBusy
	}
	dial := u.dial
	if dial == nil {
		dial = dialUDPH2
	}
	c, err := dial(target, timeout)
	if err != nil {
		return nil, err
	}
	u.mu.Lock()
	defer u.mu.Unlock()
	if u.closed || u.generation != generation {
		c.fail(errUDPConnClosed)
		return nil, errUDPConnClosed
	}
	u.conns = append(u.conns, c)
	return c, nil
}

// reset closes the connections, whose flows reopen on their next packets: the
// network changed, or the TUN started and they are not bound outside it.
func (u *udpUpstream) reset() {
	u.mu.Lock()
	defer u.mu.Unlock()
	u.dropLocked()
}

func (u *udpUpstream) close() {
	u.mu.Lock()
	defer u.mu.Unlock()
	u.closed = true
	u.dropLocked()
}

// OpenUDP opens a tunnel for UDP to authority (host:port) through the
// current server, with the current pass; a pass the proxy refuses is
// replaced as for a TCP tunnel.
func (c *Controller) OpenUDP(authority, _ string) (UDPTunnel, error) {
	host, port, err := net.SplitHostPort(authority)
	if err != nil {
		return nil, err
	}
	var lastErr, cause error
	for attempt := 0; attempt <= udpOpenRetries; attempt++ {
		var failedSession *managedSession
		ms, _, release, err := c.acquireSession()
		if err != nil {
			if c.isClosed() {
				return nil, err
			}
			lastErr, cause = err, err
		} else {
			release()
			stream, err := c.openUDPStream(ms, host, port)
			if err == nil {
				stream.traffic = c.noteTraffic
				return stream, nil
			}
			var connectErr *proxyConnectHTTPError
			if !errors.As(err, &connectErr) {
				// The connection failed, or the answer did not come: the
				// next attempt starts on a sound connection.
				lastErr = err
				if errors.Is(err, errUDPBusy) || errors.Is(err, ErrNoUsableSession) {
					return nil, err
				}
				continue
			}
			switch connectErr.statusCode {
			case http.StatusUnauthorized, http.StatusForbidden, http.StatusProxyAuthRequired:
			default:
				return nil, err
			}
			if c.refusedAgain(ms, err) {
				return nil, err
			}
			lastErr, cause = err, err
			failedSession = ms
			c.markSessionUnusable(ms)
		}
		if attempt == udpOpenRetries || c.isClosed() {
			break
		}
		logx.Debug("upstream UDP open failed; rebuilding proxy session attempt=%d err=%s", attempt+1, logx.Err(lastErr))
		if err := c.rebuildSession(failedSession, cause); err != nil {
			lastErr = fmt.Errorf("rebuilding upstream proxy session: %w", err)
		}
	}
	return nil, lastErr
}

// openUDPStream opens a stream with ms's pass, on a connection to the current
// server.
func (c *Controller) openUDPStream(ms *managedSession, host, port string) (*udpH2Stream, error) {
	c.mu.Lock()
	token, target := ms.rawToken, c.proxyURL
	c.mu.Unlock()
	conn, err := c.udp.conn(target, c.timeout)
	if err != nil {
		return nil, err
	}
	ctx, cancel := context.WithTimeout(context.Background(), udpH2OpenTimeout)
	defer cancel()
	return conn.open(ctx, token, host, port)
}

// connUDPTunnel is a connected UDP socket: a route sending UDP directly.
type connUDPTunnel struct{ net.Conn }

// An ICMP unreachable for an earlier packet shows up as an error on the next
// read or write: it says nothing about the socket, which goes on until Close.
func (t connUDPTunnel) ReadPacket(p []byte) (int, error) {
	for {
		n, err := t.Conn.Read(p)
		if err == nil || errors.Is(err, net.ErrClosed) {
			return n, err
		}
		logx.Debug("reading UDP sent directly err=%s", logx.Err(err))
		time.Sleep(udpSocketErrorPause)
	}
}

func (t connUDPTunnel) WritePacket(p []byte) error {
	_, err := t.Conn.Write(p)
	if errors.Is(err, net.ErrClosed) {
		return err
	}
	return nil
}

// countedUDPTunnel counts a tunnel's packets and says its route.
type countedUDPTunnel struct {
	UDPTunnel
	up, down *atomic.Int64
	route    string
}

// Route is the route the tunnel took.
func (t countedUDPTunnel) Route() string { return t.route }

func (t countedUDPTunnel) ReadPacket(p []byte) (int, error) {
	n, err := t.UDPTunnel.ReadPacket(p)
	t.down.Add(int64(n))
	return n, err
}

func (t countedUDPTunnel) WritePacket(p []byte) error {
	t.up.Add(int64(len(p)))
	return t.UDPTunnel.WritePacket(p)
}

// OpenUDP routes a client's UDP as OpenTunnelForClient routes its TCP:
// directly or not at all by the rules; DNS answered here (Mozilla does not
// carry port 53); otherwise through Mozilla, on the ports it carries.
func (o *RoutedOpener) OpenUDP(authority, clientKey string) (UDPTunnel, error) {
	if o.closed.Load() {
		return nil, errUDPEngineStopped
	}
	host, port, err := net.SplitHostPort(authority)
	if err != nil {
		return nil, err
	}
	switch o.decide(host) {
	case routing.Direct:
		o.direct.Add(1)
		logx.Debug("route direct target=%s udp", logx.Target(authority))
		ctx, cancel := context.WithTimeout(context.Background(), directDialTimeout)
		defer cancel()
		dial := o.dial
		if remoteClient(clientKey) && o.dialRemote != nil {
			dial = o.dialRemote
		}
		conn, err := dial(ctx, "udp", authority)
		if err != nil {
			if errors.Is(err, ErrThisMachine) {
				o.direct.Add(-1)
				o.blocked.Add(1)
			}
			return nil, err
		}
		return countedUDPTunnel{UDPTunnel: connUDPTunnel{conn}, up: &o.meter.directUp, down: &o.meter.directDown, route: RouteDirect}, nil
	case routing.Block:
		o.blocked.Add(1)
		logx.Debug("route blocked target=%s udp", logx.Target(authority))
		return nil, ErrBlockedByRule
	}
	o.proxied.Add(1)
	if port == DNSPort && o.exchange != nil {
		return countedUDPTunnel{UDPTunnel: newDNSUDPTunnel(o.exchange), up: &o.meter.up, down: &o.meter.down, route: RouteVPN}, nil
	}
	if !UDPPortAllowed(port) {
		return nil, ErrUDPPort
	}
	opener, ok := o.upstream.(udpTunnelOpener)
	if !ok {
		return nil, ErrUDPPort
	}
	tunnel, err := opener.OpenUDP(authority, clientKey)
	if err != nil {
		return nil, err
	}
	return countedUDPTunnel{UDPTunnel: tunnel, up: &o.meter.up, down: &o.meter.down, route: RouteVPN}, nil
}

const (
	// dnsUDPConcurrent bounds the DNS queries of one tunnel being answered.
	dnsUDPConcurrent = 8
	// dnsUDPTimeout bounds one query.
	dnsUDPTimeout = 10 * time.Second
)

// dnsUDPTunnel answers a client's DNS over UDP with DNS over HTTPS through
// Mozilla, which does not carry port 53.
type dnsUDPTunnel struct {
	exchange ExchangeFunc
	replies  chan []byte
	slots    chan struct{}
	ctx      context.Context
	cancel   context.CancelFunc
}

func newDNSUDPTunnel(exchange ExchangeFunc) *dnsUDPTunnel {
	ctx, cancel := context.WithCancel(context.Background())
	return &dnsUDPTunnel{
		exchange: exchange,
		replies:  make(chan []byte, dnsUDPConcurrent),
		slots:    make(chan struct{}, dnsUDPConcurrent),
		ctx:      ctx,
		cancel:   cancel,
	}
}

func (t *dnsUDPTunnel) ReadPacket(p []byte) (int, error) {
	select {
	case reply := <-t.replies:
		return copy(p, reply), nil
	case <-t.ctx.Done():
		return 0, net.ErrClosed
	}
}

func (t *dnsUDPTunnel) WritePacket(p []byte) error {
	if t.ctx.Err() != nil {
		return net.ErrClosed
	}
	select {
	case t.slots <- struct{}{}:
	default:
		return nil // too many at once: lost, like any UDP packet
	}
	query := append([]byte(nil), p...)
	go func() {
		defer func() { <-t.slots }()
		ctx, cancel := context.WithTimeout(t.ctx, dnsUDPTimeout)
		defer cancel()
		reply, err := t.exchange(ctx, query)
		if err != nil {
			logx.Debug("DNS over UDP through the proxy: %s", logx.Err(err))
			return
		}
		select {
		case t.replies <- reply:
		case <-t.ctx.Done():
		}
	}()
	return nil
}

func (t *dnsUDPTunnel) Close() error {
	t.cancel()
	return nil
}
