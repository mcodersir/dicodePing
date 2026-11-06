package proxy

import (
	"errors"
	"net"
	"sort"
	"sync"
	"sync/atomic"
	"time"
)

// Routes of a connection in the list.
const (
	RouteVPN     = "vpn"     // through Mozilla's proxy
	RouteDirect  = "direct"  // a routing rule sent it directly
	RouteBlocked = "blocked" // a routing rule refused it
	RoutePort    = "port"    // Mozilla's proxy refuses its port
	RouteFailed  = "failed"  // it did not connect
)

// keptClosed is how many closed connections the list keeps.
const keptClosed = 200

// Connection is one client connection of the proxy, as the dashboard lists
// it: open, or one of the last closed ones. The list is kept in memory only.
type Connection struct {
	ID uint64 `json:"id"`
	// Start is when the client asked for it; End when it closed (zero while
	// it is open).
	Start time.Time `json:"start"`
	End   time.Time `json:"end,omitzero"`
	// Inbound is how the client came: socks5, http, or tun.
	Inbound string `json:"inbound"`
	Client  string `json:"client"`
	Target  string `json:"target"`
	// Network is tcp or udp.
	Network string `json:"network"`
	Route   string `json:"route"`
	// Transport is h2 or h3, for a connection through Mozilla.
	Transport string `json:"transport,omitempty"`
	Up        int64  `json:"up"`
	Down      int64  `json:"down"`
}

// Connections keeps the open connections and the last closed ones. A nil
// *Connections keeps nothing.
type Connections struct {
	mu     sync.Mutex
	nextID uint64
	open   map[uint64]*trackedConn
	closed []Connection // oldest first, at most keptClosed
}

type trackedConn struct {
	c        Connection
	up, down atomic.Int64
}

// begin notes a connection the client asked for; its route is set when it
// opens or fails.
func (l *Connections) begin(inbound, client, target string) *trackedConn {
	if l == nil {
		return nil
	}
	l.mu.Lock()
	defer l.mu.Unlock()
	l.nextID++
	t := &trackedConn{c: Connection{ID: l.nextID, Start: time.Now(), Inbound: inbound, Client: client, Target: target, Network: "tcp"}}
	if l.open == nil {
		l.open = map[uint64]*trackedConn{}
	}
	l.open[t.c.ID] = t
	return t
}

// beginUDP notes a client's UDP to a destination, as begin does its TCP.
func (l *Connections) beginUDP(inbound, client, target string) *trackedConn {
	t := l.begin(inbound, client, target)
	if t != nil {
		l.mu.Lock()
		t.c.Network = "udp"
		l.mu.Unlock()
	}
	return t
}

// openedUDP sets the route of t from tunnel; the caller counts t's bytes and
// ends it.
func (l *Connections) openedUDP(t *trackedConn, tunnel UDPTunnel, transport string) {
	if l == nil || t == nil {
		return
	}
	route := RouteVPN
	if r, ok := tunnel.(interface{ Route() string }); ok && r.Route() != "" {
		route = r.Route()
	}
	l.mu.Lock()
	t.c.Route = route
	if route == RouteVPN {
		t.c.Transport = transport
	}
	l.mu.Unlock()
}

// addUp and addDown count a client's bytes.
func (t *trackedConn) addUp(n int) {
	if t != nil {
		t.up.Add(int64(n))
	}
}

func (t *trackedConn) addDown(n int) {
	if t != nil {
		t.down.Add(int64(n))
	}
}

// opened sets the route of t from conn, a tunnel the upstream opened, and
// returns conn counting t's bytes and ending t when it closes.
func (l *Connections) opened(t *trackedConn, conn net.Conn, transport string) net.Conn {
	if l == nil || t == nil {
		return conn
	}
	route := RouteVPN
	if r, ok := conn.(interface{ Route() string }); ok && r.Route() != "" {
		route = r.Route()
	}
	l.mu.Lock()
	t.c.Route = route
	if route == RouteVPN {
		t.c.Transport = transport
	}
	l.mu.Unlock()
	return wrapCounting(&countingConn{Conn: conn, up: &t.up, down: &t.down, onClose: func() { l.end(t) }})
}

// failed ends t, which did not connect, with the route err says.
func (l *Connections) failed(t *trackedConn, target string, err error) {
	if l == nil || t == nil {
		return
	}
	route := RouteFailed
	switch {
	case errors.Is(err, ErrBlockedByRule):
		route = RouteBlocked
	case portRefused(target, err), errors.Is(err, ErrUDPPort):
		route = RoutePort
	}
	l.mu.Lock()
	t.c.Route = route
	l.mu.Unlock()
	l.end(t)
}

// refused lists a connection refused before it was tried, with route.
func (l *Connections) refused(inbound, client, target, route string) {
	t := l.begin(inbound, client, target)
	if t == nil {
		return
	}
	l.mu.Lock()
	t.c.Route = route
	l.mu.Unlock()
	l.end(t)
}

// refusedUDP is refused for UDP.
func (l *Connections) refusedUDP(inbound, client, target, route string) {
	t := l.beginUDP(inbound, client, target)
	if t == nil {
		return
	}
	l.mu.Lock()
	t.c.Route = route
	l.mu.Unlock()
	l.end(t)
}

// end moves t to the closed ones.
func (l *Connections) end(t *trackedConn) {
	if l == nil || t == nil {
		return
	}
	l.mu.Lock()
	defer l.mu.Unlock()
	if _, ok := l.open[t.c.ID]; !ok {
		return
	}
	delete(l.open, t.c.ID)
	c := t.c
	c.End, c.Up, c.Down = time.Now(), t.up.Load(), t.down.Load()
	if len(l.closed) == keptClosed {
		l.closed = append(l.closed[:0], l.closed[1:]...)
	}
	l.closed = append(l.closed, c)
}

// List returns the open connections and the kept closed ones, in the
// order they started.
func (l *Connections) List() []Connection {
	if l == nil {
		return []Connection{}
	}
	l.mu.Lock()
	defer l.mu.Unlock()
	out := make([]Connection, 0, len(l.open)+len(l.closed))
	out = append(out, l.closed...)
	for _, t := range l.open {
		c := t.c
		c.Up, c.Down = t.up.Load(), t.down.Load()
		out = append(out, c)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].ID < out[j].ID })
	return out
}

// Clear forgets the closed connections.
func (l *Connections) Clear() {
	if l == nil {
		return
	}
	l.mu.Lock()
	l.closed = nil
	l.mu.Unlock()
}
