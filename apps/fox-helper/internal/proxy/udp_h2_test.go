package proxy

import (
	"bytes"
	"context"
	"errors"
	"io"
	"net"
	"net/url"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"golang.org/x/net/http2"
	"golang.org/x/net/http2/hpack"
)

// fakeUDPProxy is an HTTP/2 server speaking just enough CONNECT-UDP: it
// answers each request as answer says and echoes the packets of a stream it
// accepted, unless told otherwise.
type fakeUDPProxy struct {
	t  *testing.T
	ln net.Listener

	// settings are sent first; nil is the usual offer of extended CONNECT.
	settings []http2.Setting
	// answer decides a request: its status and Proxy-Status; nil accepts.
	answer func(fields map[string]string) (int, string)
	// silent: PINGs and packets go unanswered.
	silent atomic.Bool
	// noEcho: packets are only recorded.
	noEcho atomic.Bool

	mu       sync.Mutex
	conns    []*fakeUDPConn
	requests []map[string]string
	packets  [][]byte
	// neverIndexed: the token came as a never-indexed field.
	neverIndexed bool
	// windowUpdates adds up the WINDOW_UPDATE increments by stream.
	windowUpdates map[uint32]uint32
}

type fakeUDPConn struct {
	raw net.Conn
	fr  *http2.Framer
	mu  sync.Mutex
}

func (c *fakeUDPConn) write(fn func(*http2.Framer) error) {
	c.mu.Lock()
	defer c.mu.Unlock()
	_ = fn(c.fr)
}

func newFakeUDPProxy(t *testing.T) *fakeUDPProxy {
	t.Helper()
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	p := &fakeUDPProxy{t: t, ln: ln}
	t.Cleanup(func() {
		_ = ln.Close()
		p.mu.Lock()
		defer p.mu.Unlock()
		for _, c := range p.conns {
			_ = c.raw.Close()
		}
	})
	go func() {
		for {
			raw, err := ln.Accept()
			if err != nil {
				return
			}
			go p.serve(raw)
		}
	}()
	return p
}

func (p *fakeUDPProxy) serve(raw net.Conn) {
	preface := make([]byte, len(udpH2Preface))
	if _, err := io.ReadFull(raw, preface); err != nil || string(preface) != udpH2Preface {
		_ = raw.Close()
		return
	}
	fr := http2.NewFramer(raw, raw)
	fr.ReadMetaHeaders = hpack.NewDecoder(4096, nil)
	c := &fakeUDPConn{raw: raw, fr: fr}
	p.mu.Lock()
	p.conns = append(p.conns, c)
	settings := p.settings
	p.mu.Unlock()
	if settings == nil {
		settings = []http2.Setting{{ID: http2.SettingEnableConnectProtocol, Val: 1}}
	}
	c.write(func(f *http2.Framer) error { return f.WriteSettings(settings...) })
	parts := map[uint32][]byte{}
	for {
		frame, err := fr.ReadFrame()
		if err != nil {
			return
		}
		switch f := frame.(type) {
		case *http2.SettingsFrame:
			if !f.IsAck() {
				c.write(func(fr *http2.Framer) error { return fr.WriteSettingsAck() })
			}
		case *http2.WindowUpdateFrame:
			p.mu.Lock()
			if p.windowUpdates == nil {
				p.windowUpdates = map[uint32]uint32{}
			}
			p.windowUpdates[f.StreamID] += f.Increment
			p.mu.Unlock()
		case *http2.PingFrame:
			if !f.IsAck() && !p.silent.Load() {
				data := f.Data
				c.write(func(fr *http2.Framer) error { return fr.WritePing(true, data) })
			}
		case *http2.MetaHeadersFrame:
			fields := map[string]string{}
			for _, field := range f.Fields {
				fields[field.Name] = field.Value
				if field.Name == "proxy-authorization" && field.Sensitive {
					p.mu.Lock()
					p.neverIndexed = true
					p.mu.Unlock()
				}
			}
			p.mu.Lock()
			p.requests = append(p.requests, fields)
			answer := p.answer
			p.mu.Unlock()
			status, proxyStatus := 200, ""
			if answer != nil {
				status, proxyStatus = answer(fields)
			}
			c.respond(f.StreamID, status, proxyStatus)
		case *http2.DataFrame:
			data := append(parts[f.StreamID], f.Data()...)
			for {
				kind, n1 := quicVarint(data)
				if n1 == 0 {
					break
				}
				size, n2 := quicVarint(data[n1:])
				if n2 == 0 || len(data) < n1+n2+int(size) {
					break
				}
				capsule := data[n1+n2 : n1+n2+int(size)]
				if kind == 0 {
					packet := append([]byte(nil), capsule[1:]...)
					p.mu.Lock()
					p.packets = append(p.packets, packet)
					p.mu.Unlock()
					if !p.noEcho.Load() && !p.silent.Load() {
						id := f.StreamID
						reply := datagramCapsule(append([]byte("echo:"), packet...))
						c.write(func(fr *http2.Framer) error { return fr.WriteData(id, false, reply) })
					}
				}
				data = data[n1+n2+int(size):]
			}
			parts[f.StreamID] = append([]byte(nil), data...)
		}
	}
}

func (c *fakeUDPConn) respond(id uint32, status int, proxyStatus string) {
	var block bytes.Buffer
	enc := hpack.NewEncoder(&block)
	_ = enc.WriteField(hpack.HeaderField{Name: ":status", Value: strconv.Itoa(status)})
	if proxyStatus != "" {
		_ = enc.WriteField(hpack.HeaderField{Name: "proxy-status", Value: proxyStatus})
	}
	c.write(func(fr *http2.Framer) error {
		return fr.WriteHeaders(http2.HeadersFrameParam{StreamID: id, BlockFragment: block.Bytes(), EndHeaders: true})
	})
}

// datagramCapsule is a packet as a DATAGRAM capsule with context ID 0.
func datagramCapsule(p []byte) []byte {
	c := appendQUICVarint(nil, 0)
	c = appendQUICVarint(c, uint64(len(p)+1))
	c = append(c, 0)
	return append(c, p...)
}

// dial connects a client to the fake proxy.
func (p *fakeUDPProxy) dial(t *testing.T) *udpH2Conn {
	t.Helper()
	conn, err := p.tryDial()
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { conn.fail(errUDPConnClosed) })
	return conn
}

func (p *fakeUDPProxy) tryDial() (*udpH2Conn, error) {
	raw, err := net.Dial("tcp", p.ln.Addr().String())
	if err != nil {
		return nil, err
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	conn, err := newUDPH2Conn(ctx, raw, "proxy.test:2499")
	if err != nil {
		_ = raw.Close()
	}
	return conn, err
}

func (p *fakeUDPProxy) lastRequest() map[string]string {
	p.mu.Lock()
	defer p.mu.Unlock()
	if len(p.requests) == 0 {
		return nil
	}
	return p.requests[len(p.requests)-1]
}

func openStream(t *testing.T, c *udpH2Conn, host, port string) *udpH2Stream {
	t.Helper()
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	s, err := c.open(ctx, "the-token", host, port)
	if err != nil {
		t.Fatalf("open %s:%s: %v", host, port, err)
	}
	return s
}

// readPacket reads one packet with a deadline.
func readPacket(t *testing.T, tunnel UDPTunnel) string {
	t.Helper()
	type result struct {
		data string
		err  error
	}
	got := make(chan result, 1)
	go func() {
		b := make([]byte, 70000)
		n, err := tunnel.ReadPacket(b)
		got <- result{string(b[:n]), err}
	}()
	select {
	case r := <-got:
		if r.err != nil {
			t.Fatalf("read: %v", r.err)
		}
		return r.data
	case <-time.After(5 * time.Second):
		t.Fatal("no packet within 5 s")
		return ""
	}
}

// The request is RFC 9298's over RFC 8441's extended CONNECT.
func TestConnectUDPRequest(t *testing.T) {
	p := newFakeUDPProxy(t)
	c := p.dial(t)
	s := openStream(t, c, "2001:db8::1", "3478")
	defer s.Close()
	for name, want := range map[string]string{
		":method":             "CONNECT",
		":protocol":           "connect-udp",
		":scheme":             "https",
		":authority":          "proxy.test:2499",
		":path":               "/.well-known/masque/udp/2001%3Adb8%3A%3A1/3478/",
		"capsule-protocol":    "?1",
		"proxy-authorization": "Bearer the-token",
	} {
		if got := p.lastRequest()[name]; got != want {
			t.Errorf("%s = %q, want %q", name, got, want)
		}
	}
	p.mu.Lock()
	defer p.mu.Unlock()
	if !p.neverIndexed {
		t.Error("the token could end up in HPACK's table")
	}
}

func TestConnectUDPPath(t *testing.T) {
	for _, c := range []struct{ host, port, want string }{
		{"1.2.3.4", "443", "/.well-known/masque/udp/1.2.3.4/443/"},
		{"stun.example.com", "3478", "/.well-known/masque/udp/stun.example.com/3478/"},
		{"::1", "53", "/.well-known/masque/udp/%3A%3A1/53/"},
		{"a/b?c", "1", "/.well-known/masque/udp/a%2Fb%3Fc/1/"},
	} {
		if got := connectUDPPath(c.host, c.port); got != c.want {
			t.Errorf("%s %s: %s, want %s", c.host, c.port, got, c.want)
		}
	}
}

func TestQUICVarint(t *testing.T) {
	for _, v := range []uint64{0, 1, 63, 64, 16383, 16384, 1<<30 - 1, 1 << 30, 1 << 40} {
		b := appendQUICVarint(nil, v)
		got, n := quicVarint(b)
		if got != v || n != len(b) {
			t.Errorf("%d came back as %d in %d of %d bytes", v, got, n, len(b))
		}
		if _, n := quicVarint(b[:len(b)-1]); n != 0 {
			t.Errorf("a cut %d parsed", v)
		}
	}
}

func TestPacketsGoBothWays(t *testing.T) {
	p := newFakeUDPProxy(t)
	c := p.dial(t)
	s := openStream(t, c, "peer.example", "443")
	defer s.Close()
	var counted atomic.Int64
	s.traffic = func(n int) { counted.Add(int64(n)) }
	for _, packet := range []string{"one", "", strings.Repeat("x", 1400), strings.Repeat("y", 20000)} {
		if err := s.WritePacket([]byte(packet)); err != nil {
			t.Fatal(err)
		}
		if got := readPacket(t, s); got != "echo:"+packet {
			t.Fatalf("read %d bytes for a packet of %d", len(got), len(packet))
		}
	}
	if counted.Load() == 0 {
		t.Error("nothing was counted")
	}
}

// A capsule may come in several frames, and several in one; other capsule
// types and context IDs are skipped.
func TestCapsulesAcrossFrames(t *testing.T) {
	p := newFakeUDPProxy(t)
	p.noEcho.Store(true)
	c := p.dial(t)
	s := openStream(t, c, "peer.example", "443")
	defer s.Close()
	p.mu.Lock()
	server := p.conns[0]
	p.mu.Unlock()
	id := s.id.Load()

	whole := append(datagramCapsule([]byte("first")), datagramCapsule([]byte("second"))...)
	// An unknown capsule type, and a datagram of another context.
	other := append(appendQUICVarint(appendQUICVarint(nil, 0x2a), 3), "abc"...)
	otherContext := append(appendQUICVarint(appendQUICVarint(nil, 0), 3), 5, 'n', 'o')
	stream := append(append(append(whole, other...), otherContext...), datagramCapsule([]byte("third"))...)
	for i := 0; i < len(stream); i += 3 {
		chunk := stream[i:min(i+3, len(stream))]
		server.write(func(fr *http2.Framer) error { return fr.WriteData(id, false, chunk) })
	}
	for _, want := range []string{"first", "second", "third"} {
		if got := readPacket(t, s); got != want {
			t.Fatalf("got %q, want %q", got, want)
		}
	}
}

// A capsule too large to be a packet ends the stream, not the connection.
func TestOversizedCapsuleEndsItsStream(t *testing.T) {
	p := newFakeUDPProxy(t)
	p.noEcho.Store(true)
	c := p.dial(t)
	s := openStream(t, c, "peer.example", "443")
	p.mu.Lock()
	server := p.conns[0]
	p.mu.Unlock()
	id := s.id.Load()
	server.write(func(fr *http2.Framer) error {
		return fr.WriteData(id, false, appendQUICVarint(appendQUICVarint(nil, 0), 1<<20))
	})
	select {
	case <-s.done:
	case <-time.After(5 * time.Second):
		t.Fatal("the stream goes on")
	}
	if c.ended() {
		t.Fatal("the connection ended with the stream")
	}
}

func TestRefusalsSayWhy(t *testing.T) {
	p := newFakeUDPProxy(t)
	p.answer = func(fields map[string]string) (int, string) {
		if strings.Contains(fields[":path"], "/53/") {
			return 502, "Fastly; error=destination_ip_prohibited"
		}
		return 401, ""
	}
	c := p.dial(t)
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	_, err := c.open(ctx, "t", "1.1.1.1", "53")
	var refused *proxyConnectHTTPError
	if !errors.As(err, &refused) || refused.statusCode != 502 || !strings.Contains(refused.body, "destination_ip_prohibited") {
		t.Fatalf("err = %v", err)
	}
	_, err = c.open(ctx, "t", "1.1.1.1", "443")
	if !errors.As(err, &refused) || refused.statusCode != 401 {
		t.Fatalf("err = %v", err)
	}
	if c.ended() {
		t.Fatal("a refusal ended the connection")
	}
}

func TestAProxyWithoutExtendedConnectIsRefused(t *testing.T) {
	p := newFakeUDPProxy(t)
	p.settings = []http2.Setting{{ID: http2.SettingMaxConcurrentStreams, Val: 10}}
	if _, err := p.tryDial(); !errors.Is(err, errUDPNoConnectProtocol) {
		t.Fatalf("err = %v", err)
	}
}

// The server's reset and end of a stream reach its reader.
func TestAResetEndsTheStream(t *testing.T) {
	p := newFakeUDPProxy(t)
	c := p.dial(t)
	s := openStream(t, c, "peer.example", "443")
	p.mu.Lock()
	server := p.conns[0]
	p.mu.Unlock()
	id := s.id.Load()
	server.write(func(fr *http2.Framer) error { return fr.WriteRSTStream(id, http2.ErrCodeRefusedStream) })
	b := make([]byte, 10)
	if _, err := s.ReadPacket(b); !errors.Is(err, errUDPStreamReset) {
		t.Fatalf("err = %v", err)
	}
	if err := s.WritePacket([]byte("late")); err == nil {
		t.Fatal("a write on a reset stream did not say so")
	}
}

// After GOAWAY no stream opens on the connection, and it reports so; those the
// server still serves go on.
func TestGoAwayStopsNewStreams(t *testing.T) {
	p := newFakeUDPProxy(t)
	c := p.dial(t)
	first := openStream(t, c, "a.example", "443")
	second := openStream(t, c, "b.example", "443")
	p.mu.Lock()
	server := p.conns[0]
	p.mu.Unlock()
	firstID := first.id.Load()
	server.write(func(fr *http2.Framer) error { return fr.WriteGoAway(firstID, http2.ErrCodeNo, nil) })
	select {
	case <-second.done:
	case <-time.After(5 * time.Second):
		t.Fatal("a stream past GOAWAY's last goes on")
	}
	deadline := time.Now().Add(5 * time.Second)
	for c.usable() {
		if time.Now().After(deadline) {
			t.Fatal("the connection still takes streams")
		}
		time.Sleep(5 * time.Millisecond)
	}
	if err := first.WritePacket([]byte("on")); err != nil {
		t.Fatal(err)
	}
	if got := readPacket(t, first); got != "echo:on" {
		t.Fatalf("got %q", got)
	}
}

func shortUDPTimes(t *testing.T) {
	t.Helper()
	ping, dead, idle := udpH2PingEvery, udpH2DeadAfter, udpH2IdleClose
	udpH2PingEvery, udpH2DeadAfter, udpH2IdleClose = 20*time.Millisecond, 150*time.Millisecond, 200*time.Millisecond
	t.Cleanup(func() { udpH2PingEvery, udpH2DeadAfter, udpH2IdleClose = ping, dead, idle })
}

// A connection that stops answering is found, and ends its streams.
func TestASilentConnectionIsClosed(t *testing.T) {
	shortUDPTimes(t)
	p := newFakeUDPProxy(t)
	c := p.dial(t)
	s := openStream(t, c, "peer.example", "443")
	time.Sleep(3 * udpH2DeadAfter)
	if c.ended() {
		t.Fatal("a connection that answers its PINGs died")
	}
	p.silent.Store(true)
	select {
	case <-s.done:
	case <-time.After(5 * time.Second):
		t.Fatal("the stream outlived the connection")
	}
	if !c.ended() || c.usable() {
		t.Fatal("the connection goes on")
	}
}

// Nothing stays open toward Mozilla while no program sends UDP.
func TestAnUnusedConnectionCloses(t *testing.T) {
	shortUDPTimes(t)
	p := newFakeUDPProxy(t)
	c := p.dial(t)
	s := openStream(t, c, "peer.example", "443")
	time.Sleep(2 * udpH2IdleClose)
	if c.ended() {
		t.Fatal("a connection with a stream closed")
	}
	_ = s.Close()
	deadline := time.Now().Add(5 * time.Second)
	for !c.ended() {
		if time.Now().After(deadline) {
			t.Fatal("the unused connection stays")
		}
		time.Sleep(5 * time.Millisecond)
	}
}

// A packet the window does not allow is dropped at once, and the next one goes
// when the window opens; nothing waits.
func TestAFullWindowDropsPackets(t *testing.T) {
	p := newFakeUDPProxy(t)
	p.noEcho.Store(true)
	c := p.dial(t)
	s := openStream(t, c, "peer.example", "443")
	defer s.Close()
	big := make([]byte, 30000)
	start := time.Now()
	for range 5 {
		if err := s.WritePacket(big); err != nil {
			t.Fatal(err)
		}
	}
	if d := time.Since(start); d > time.Second {
		t.Fatalf("the writes waited %s", d)
	}
	waitFor := func(want int) {
		t.Helper()
		deadline := time.Now().Add(5 * time.Second)
		for {
			p.mu.Lock()
			n := len(p.packets)
			p.mu.Unlock()
			if n == want {
				return
			}
			if time.Now().After(deadline) {
				t.Fatalf("%d packets arrived, want %d", n, want)
			}
			time.Sleep(5 * time.Millisecond)
		}
	}
	// The initial window of 65535 takes two of these, and the others drop.
	waitFor(2)
	time.Sleep(50 * time.Millisecond)
	waitFor(2)

	p.mu.Lock()
	server := p.conns[0]
	p.mu.Unlock()
	id := s.id.Load()
	server.write(func(fr *http2.Framer) error {
		if err := fr.WriteWindowUpdate(0, 100000); err != nil {
			return err
		}
		return fr.WriteWindowUpdate(id, 100000)
	})
	deadline := time.Now().Add(5 * time.Second)
	for {
		_ = s.WritePacket(big)
		p.mu.Lock()
		n := len(p.packets)
		p.mu.Unlock()
		if n > 2 {
			break
		}
		if time.Now().After(deadline) {
			t.Fatal("the open window took nothing")
		}
		time.Sleep(10 * time.Millisecond)
	}
}

// The windows offered are topped up, so that a long download goes on.
func TestTheReceiveWindowIsToppedUp(t *testing.T) {
	p := newFakeUDPProxy(t)
	p.noEcho.Store(true)
	c := p.dial(t)
	s := openStream(t, c, "peer.example", "443")
	defer s.Close()
	p.mu.Lock()
	server := p.conns[0]
	p.mu.Unlock()
	id := s.id.Load()
	chunk := datagramCapsule(make([]byte, 16000))
	go func() {
		for range 40 {
			server.write(func(fr *http2.Framer) error { return fr.WriteData(id, false, chunk) })
		}
	}()
	buf := make([]byte, 20000)
	for range 40 {
		if _, err := s.ReadPacket(buf); err != nil {
			t.Fatal(err)
		}
	}
	deadline := time.Now().Add(5 * time.Second)
	for {
		p.mu.Lock()
		stream, conn := p.windowUpdates[id], p.windowUpdates[0]
		p.mu.Unlock()
		if stream >= udpH2WindowStep && conn > udpH2ConnWindow-65535 {
			break
		}
		if time.Now().After(deadline) {
			t.Fatalf("topped up by %d on the stream, %d on the connection", stream, conn)
		}
		time.Sleep(5 * time.Millisecond)
	}
}

// A stream given up before its request was written leaves nothing behind.
func TestAnOpenGivenUpLeavesNoStream(t *testing.T) {
	p := newFakeUDPProxy(t)
	c := p.dial(t)
	s := &udpH2Stream{c: c, opened: make(chan error, 1), in: make(chan []byte, 1), done: make(chan struct{})}
	c.mu.Lock()
	c.pendingOpens++
	c.mu.Unlock()
	c.endStream(s, context.Canceled)
	wrote := make(chan struct{})
	c.control(func() error {
		defer close(wrote)
		return c.writeHeaders(s, "t", "a.example", "443")
	})
	<-wrote
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.pendingOpens != 0 || len(c.streams) != 0 {
		t.Fatalf("pending %d, streams %d", c.pendingOpens, len(c.streams))
	}
}

// udpUpstream keeps connections for one server: another server's are closed,
// an ended one is replaced, and a full one gets a second.
func TestUDPUpstreamPicksAConnection(t *testing.T) {
	p := newFakeUDPProxy(t)
	p.settings = []http2.Setting{
		{ID: http2.SettingEnableConnectProtocol, Val: 1},
		{ID: http2.SettingMaxConcurrentStreams, Val: 1},
	}
	var dials atomic.Int32
	u := &udpUpstream{dial: func(*url.URL, time.Duration) (*udpH2Conn, error) {
		dials.Add(1)
		return p.tryDial()
	}}
	t.Cleanup(u.close)
	target := &url.URL{Scheme: "https", Host: "proxy.test:2499"}
	first, err := u.conn(target, time.Second)
	if err != nil {
		t.Fatal(err)
	}
	if again, _ := u.conn(target, time.Second); again != first || dials.Load() != 1 {
		t.Fatalf("no reuse: %d dials", dials.Load())
	}
	// One stream per connection here: the next one needs another.
	s := openStream(t, first, "a.example", "443")
	defer s.Close()
	second, err := u.conn(target, time.Second)
	if err != nil {
		t.Fatal(err)
	}
	if second == first || dials.Load() != 2 {
		t.Fatalf("a full connection was given: %d dials", dials.Load())
	}
	// Another server: both go.
	other := &url.URL{Scheme: "https", Host: "other.test:2499"}
	third, err := u.conn(other, time.Second)
	if err != nil {
		t.Fatal(err)
	}
	if !first.ended() || !second.ended() || third.ended() {
		t.Fatal("the old server's connections stay")
	}
	// A reset (the network changed) closes the connections; the next dials.
	u.reset()
	if !third.ended() {
		t.Fatal("a reset left a connection")
	}
	if c, err := u.conn(other, time.Second); err != nil || c.ended() {
		t.Fatalf("after a reset: %v", err)
	}
	u.close()
	if _, err := u.conn(other, time.Second); !errors.Is(err, ErrNoUsableSession) {
		t.Fatalf("after close: %v", err)
	}
}

// udpController is a controller whose UDP goes to p.
func udpController(t *testing.T, p *fakeUDPProxy, token string) *Controller {
	t.Helper()
	c := &Controller{
		proxyURL: &url.URL{Scheme: "https", Host: "proxy.test:2499"},
		current:  &managedSession{session: newMortalProxySession(), rawToken: token, expiresAt: time.Now().Add(time.Hour), accepting: true},
	}
	c.udp.dial = func(*url.URL, time.Duration) (*udpH2Conn, error) { return p.tryDial() }
	t.Cleanup(c.udp.close)
	return c
}

func TestControllerOpensUDPWithItsPass(t *testing.T) {
	p := newFakeUDPProxy(t)
	c := udpController(t, p, "pass-1")
	tunnel, err := c.OpenUDP("stun.example:3478", "")
	if err != nil {
		t.Fatal(err)
	}
	defer tunnel.Close()
	if got := p.lastRequest()["proxy-authorization"]; got != "Bearer pass-1" {
		t.Fatalf("authorization %q", got)
	}
	if err := tunnel.WritePacket([]byte("hello")); err != nil {
		t.Fatal(err)
	}
	if got := readPacket(t, tunnel); got != "echo:hello" {
		t.Fatalf("got %q", got)
	}
	if c.trafficSinceReading.Load() == 0 {
		t.Error("the traffic does not count toward the quota")
	}
	// A destination the proxy refuses is the client's answer, with no new pass.
	p.answer = func(map[string]string) (int, string) { return 502, "x" }
	if _, err := c.OpenUDP("1.1.1.1:53", ""); err == nil {
		t.Fatal("no refusal")
	}
	if c.CurrentToken() != "pass-1" {
		t.Fatal("a refused destination changed the pass")
	}
}

// A pass the proxy refuses is replaced, as for a TCP tunnel, and the UDP opens
// with the new one.
func TestControllerReplacesARefusedPassForUDP(t *testing.T) {
	p := newFakeUDPProxy(t)
	p.answer = func(fields map[string]string) (int, string) {
		if fields["proxy-authorization"] == "Bearer new-pass" {
			return 200, ""
		}
		return 401, ""
	}
	c := udpController(t, p, "old-pass")
	c.refreshSession = func() error {
		c.swapSession(newMortalProxySession(), "new-pass", time.Now().Add(time.Hour))
		return nil
	}
	tunnel, err := c.OpenUDP("stun.example:3478", "")
	if err != nil {
		t.Fatal(err)
	}
	defer tunnel.Close()
	if c.CurrentToken() != "new-pass" {
		t.Fatalf("the pass is %q", c.CurrentToken())
	}
}

// A connection that died is replaced, and the flow opens on the new one.
func TestControllerRedialsADeadUDPConnection(t *testing.T) {
	p := newFakeUDPProxy(t)
	c := udpController(t, p, "pass")
	first, err := c.OpenUDP("a.example:443", "")
	if err != nil {
		t.Fatal(err)
	}
	defer first.Close()
	first.(*udpH2Stream).c.fail(errUDPConnClosed)
	second, err := c.OpenUDP("a.example:443", "")
	if err != nil {
		t.Fatal(err)
	}
	defer second.Close()
	if err := second.WritePacket([]byte("again")); err != nil {
		t.Fatal(err)
	}
	if got := readPacket(t, second); got != "echo:again" {
		t.Fatalf("got %q", got)
	}
}
