package proxy

import (
	"errors"
	"net"
	"net/http"
	"sync/atomic"
	"testing"
)

// opener answers every tunnel with conn and err.
type opener struct {
	conn net.Conn
	err  error
}

func (o opener) OpenTunnel(string) (net.Conn, error) { return o.conn, o.err }

// The list shows a connection open with its route, protocol, and bytes,
// then closed, in the order they started; refused ones show why.
func TestTheConnectionsAreListed(t *testing.T) {
	conns := &Connections{}
	client, _ := net.Pipe()
	defer client.Close()

	tunnel, far := net.Pipe()
	go func() {
		buf := make([]byte, 5)
		_, _ = far.Read(buf)
		_, _ = far.Write([]byte("hi"))
	}()
	s := &SOCKSServer{Conns: conns, Transport: func() string { return "h2" }, upstream: opener{conn: countRouted(tunnel, new(atomic.Int64), new(atomic.Int64), RouteDirect)}}
	conn, err := s.openTarget(client, "example.com:443", "127.0.0.1:5000", "socks5")
	if err != nil {
		t.Fatal(err)
	}
	_, _ = conn.Write([]byte("hello"))
	buf := make([]byte, 2)
	_, _ = conn.Read(buf)

	list := conns.List()
	if len(list) != 1 || list[0].Route != RouteDirect || list[0].Target != "example.com:443" || list[0].Inbound != "socks5" ||
		list[0].Up != 5 || list[0].Down != 2 || !list[0].End.IsZero() || list[0].Transport != "" || list[0].Network != "tcp" {
		t.Fatalf("open: %+v", list)
	}
	_ = conn.Close()
	_ = conn.Close()
	if list = conns.List(); len(list) != 1 || list[0].End.IsZero() || list[0].Up != 5 {
		t.Fatalf("closed: %+v", list)
	}

	// Through Mozilla: the protocol; refused: why.
	s.upstream = opener{conn: &fakeNetConn{}}
	vpn, err := s.openTarget(client, "a.com:443", "127.0.0.1:5001", "http")
	if err != nil {
		t.Fatal(err)
	}
	s.upstream = opener{err: ErrBlockedByRule}
	_, _ = s.openTarget(client, "b.com:443", "127.0.0.1:5002", "http")
	s.upstream = opener{err: &proxyConnectHTTPError{statusCode: http.StatusBadGateway}}
	_, _ = s.openTarget(client, "c.com:22", "127.0.0.1:5003", "http")
	s.upstream = opener{err: errors.New("no route")}
	_, _ = s.openTarget(client, "d.com:443", "127.0.0.1:5004", "http")
	s.Inbound = "tun"
	s.Conns.refused(s.inbound("socks5"), "198.18.0.1:5005", "e.com:25", RoutePort)

	got := map[string]string{}
	for _, c := range conns.List() {
		got[c.Target] = c.Route + " " + c.Transport + " " + c.Inbound
	}
	want := map[string]string{
		"example.com:443": "direct  socks5",
		"a.com:443":       "vpn h2 http",
		"b.com:443":       "blocked  http",
		"c.com:22":        "port  http",
		"d.com:443":       "failed  http",
		"e.com:25":        "port  tun",
	}
	for k, v := range want {
		if got[k] != v {
			t.Errorf("%s: %q, want %q", k, got[k], v)
		}
	}
	if list := conns.List(); list[0].Target != "example.com:443" || list[1].Target != "a.com:443" || list[5].Target != "e.com:25" {
		t.Errorf("not in the order they started: %+v", list)
	}
	_ = vpn.Close()
	conns.Clear()
	if list := conns.List(); len(list) != 0 {
		t.Errorf("after Clear: %+v", list)
	}
}

// Only the last closed ones are kept.
func TestTheClosedConnectionsAreCapped(t *testing.T) {
	conns := &Connections{}
	for range keptClosed + 50 {
		conns.refused("socks5", "c", "x:1", RouteFailed)
	}
	if list := conns.List(); len(list) != keptClosed || list[0].ID != 51 || list[keptClosed-1].ID != keptClosed+50 {
		t.Fatalf("%d kept, from %d to %d", len(list), list[0].ID, list[len(list)-1].ID)
	}
	var none *Connections
	none.refused("socks5", "c", "x:1", RouteFailed)
	if len(none.List()) != 0 {
		t.Fatal("a nil list kept something")
	}
}
