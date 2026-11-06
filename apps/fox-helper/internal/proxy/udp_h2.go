package proxy

import (
	"bufio"
	"bytes"
	"context"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"strconv"
	"sync"
	"sync/atomic"
	"time"

	"golang.org/x/net/http2"
	"golang.org/x/net/http2/hpack"

	"dicodeping/fox/internal/controlplane"
	"dicodeping/fox/internal/logx"
)

// CONNECT-UDP (RFC 9298) over HTTP/2: Mozilla's proxy carries UDP in an
// extended CONNECT stream (RFC 8441), each packet a DATAGRAM capsule (RFC
// 9297) with context ID 0.
//
// This is a small HTTP/2 client of its own, on x/net's framer, for two
// reasons. Under Go 1.27 x/net's http2.Transport hands over to net/http,
// which refuses the :protocol pseudo-header. And UDP belongs on a connection
// of its own: there a bulk download through a TCP tunnel does not delay a
// call's packets, and a packet the connection cannot take now is dropped, as
// UDP may be, instead of waiting behind the others.

const (
	// udpH2Preface starts an HTTP/2 connection.
	udpH2Preface = "PRI * HTTP/2.0\r\n\r\nSM\r\n\r\n"

	// udpH2StreamWindow and udpH2ConnWindow are the receive windows offered.
	// Packets are consumed as they arrive (dropped when the client is slow),
	// so the windows only have to outrun the network.
	udpH2StreamWindow = 1 << 20
	udpH2ConnWindow   = 16 << 20
	// udpH2WindowStep is how much is consumed before the window is topped up.
	udpH2WindowStep = 256 << 10
	// udpH2MaxFrame is the largest frame this client takes.
	udpH2MaxFrame = 64 << 10

	// udpH2MaxCapsule bounds a capsule: a UDP packet and its context ID.
	udpH2MaxCapsule = 65535 + 16
	// udpH2MaxQueued bounds what waits to be written, in bytes: more would
	// only delay the packets behind it (a call's, or QUIC's own congestion
	// control), so packets beyond it are dropped.
	udpH2MaxQueued = 256 << 10
	// udpH2ReadQueue is how many received packets of a stream wait for the
	// client; more are dropped.
	udpH2ReadQueue = 256

	// udpH2DefaultStreams is the streams per connection when the server names
	// no limit.
	udpH2DefaultStreams = 100
)

// Vars so that tests can shorten them.
var (
	// udpH2PingEvery spaces the keepalive PINGs; a connection silent for
	// udpH2DeadAfter counts as dead (its flows reopen on their next packet).
	udpH2PingEvery = 5 * time.Second
	udpH2DeadAfter = 15 * time.Second
	// udpH2IdleClose closes a connection without streams: nothing is kept
	// open toward Mozilla when no program sends UDP.
	udpH2IdleClose = time.Minute
	// udpH2WriteTimeout bounds one write to the network.
	udpH2WriteTimeout = 15 * time.Second
	// udpH2OpenTimeout bounds waiting for the answer to a CONNECT-UDP.
	udpH2OpenTimeout = 15 * time.Second
)

var (
	errUDPConnClosed = errors.New("upstream UDP connection closed")
	// errUDPNoConnectProtocol is a server that does not offer extended CONNECT.
	errUDPNoConnectProtocol = errors.New("proxy does not offer extended CONNECT")
	errUDPStreamReset       = errors.New("proxy reset the UDP stream")
	errUDPStreamEnded       = errors.New("proxy ended the UDP stream")
)

// udpH2Conn is one HTTP/2 connection to Mozilla's proxy, carrying CONNECT-UDP
// streams. Only writeLoop writes to the connection (HPACK needs one order),
// and only readLoop reads from it.
type udpH2Conn struct {
	conn      net.Conn
	bw        *bufio.Writer
	fr        *http2.Framer
	authority string
	// uploading, when set, says that packets sent may be why nothing arrives
	// (watchedConn.uploading).
	uploading func() bool

	// Written only by writeLoop.
	henc    *hpack.Encoder
	hbuf    bytes.Buffer
	nextID  uint32
	maxSent uint32

	ctrl   chan func() error
	data   chan udpH2Packet
	done   chan struct{}
	failed sync.Once
	// lastRead is the UnixNano of the last frame read.
	lastRead atomic.Int64
	// connUnacked is read data the connection's window was not topped up
	// for; readLoop's alone.
	connUnacked uint32

	mu             sync.Mutex
	err            error
	streams        map[uint32]*udpH2Stream
	pendingOpens   int
	draining       bool
	idleSince      time.Time
	sendWindow     int64
	streamWindow   int64
	maxFrameSize   uint32
	maxStreams     uint32
	queued         int
	connectAllowed bool
}

// udpH2Packet is a capsule waiting for writeLoop.
type udpH2Packet struct {
	stream  *udpH2Stream
	capsule []byte
}

// dialUDPH2 connects to the proxy and waits for its SETTINGS, which must
// offer extended CONNECT.
func dialUDPH2(proxyURL *url.URL, timeout time.Duration) (*udpH2Conn, error) {
	proxyHost := proxyURL.Host
	if proxyURL.Port() == "" {
		proxyHost = proxyURL.Hostname() + ":443"
	}
	ctx := context.Background()
	if timeout > 0 {
		var cancel context.CancelFunc
		ctx, cancel = context.WithTimeout(ctx, timeout)
		defer cancel()
	}
	conn, watched, err := dialUpstreamTLS(ctx, proxyURL, proxyHost)
	if err != nil {
		return nil, err
	}
	c, err := newUDPH2Conn(ctx, conn, proxyHost)
	if err != nil {
		_ = conn.Close()
		return nil, err
	}
	c.uploading = watched.uploading
	logx.Info("upstream UDP connection established proxy=%s", proxyHost)
	return c, nil
}

// newUDPH2Conn runs HTTP/2 on conn; authority names the proxy in requests.
func newUDPH2Conn(ctx context.Context, conn net.Conn, authority string) (*udpH2Conn, error) {
	bw := bufio.NewWriterSize(conn, 64<<10)
	c := &udpH2Conn{
		conn:         conn,
		bw:           bw,
		fr:           http2.NewFramer(bw, conn),
		authority:    authority,
		nextID:       1,
		ctrl:         make(chan func() error, 256),
		data:         make(chan udpH2Packet, 4096),
		done:         make(chan struct{}),
		streams:      map[uint32]*udpH2Stream{},
		idleSince:    time.Now(),
		sendWindow:   65535,
		streamWindow: 65535,
		maxFrameSize: 16384,
		maxStreams:   udpH2DefaultStreams,
	}
	c.henc = hpack.NewEncoder(&c.hbuf)
	c.fr.ReadMetaHeaders = hpack.NewDecoder(4096, nil)
	c.fr.MaxHeaderListSize = 64 << 10
	c.fr.SetMaxReadFrameSize(udpH2MaxFrame)
	c.lastRead.Store(time.Now().UnixNano())

	deadline, ok := ctx.Deadline()
	if ok {
		_ = conn.SetDeadline(deadline)
	} else {
		_ = conn.SetDeadline(time.Now().Add(udpH2OpenTimeout))
	}
	if _, err := io.WriteString(bw, udpH2Preface); err != nil {
		return nil, err
	}
	if err := c.fr.WriteSettings(
		http2.Setting{ID: http2.SettingEnablePush, Val: 0},
		http2.Setting{ID: http2.SettingInitialWindowSize, Val: udpH2StreamWindow},
		http2.Setting{ID: http2.SettingMaxFrameSize, Val: udpH2MaxFrame},
	); err != nil {
		return nil, err
	}
	if err := c.fr.WriteWindowUpdate(0, udpH2ConnWindow-65535); err != nil {
		return nil, err
	}
	if err := bw.Flush(); err != nil {
		return nil, err
	}
	// The server's first frame is its SETTINGS (RFC 9113 3.4).
	first, err := c.fr.ReadFrame()
	if err != nil {
		return nil, fmt.Errorf("reading the proxy's settings: %w", err)
	}
	settings, ok := first.(*http2.SettingsFrame)
	if !ok || settings.IsAck() {
		return nil, fmt.Errorf("the proxy started with a %s frame", first.Header().Type)
	}
	if err := c.applySettings(settings); err != nil {
		return nil, err
	}
	if !c.connectAllowed {
		return nil, errUDPNoConnectProtocol
	}
	if err := c.fr.WriteSettingsAck(); err != nil {
		return nil, err
	}
	if err := bw.Flush(); err != nil {
		return nil, err
	}
	_ = conn.SetDeadline(time.Time{})
	go c.readLoop()
	go c.writeLoop()
	go c.keepAlive()
	return c, nil
}

// applySettings takes the server's settings.
func (c *udpH2Conn) applySettings(f *http2.SettingsFrame) error {
	c.mu.Lock()
	defer c.mu.Unlock()
	return f.ForeachSetting(func(s http2.Setting) error {
		switch s.ID {
		case http2.SettingEnableConnectProtocol:
			c.connectAllowed = s.Val == 1
		case http2.SettingMaxConcurrentStreams:
			c.maxStreams = s.Val
		case http2.SettingMaxFrameSize:
			c.maxFrameSize = s.Val
		case http2.SettingInitialWindowSize:
			delta := int64(s.Val) - c.streamWindow
			c.streamWindow = int64(s.Val)
			for _, stream := range c.streams {
				stream.sendWindow += delta
			}
		case http2.SettingHeaderTableSize:
			size := s.Val
			// The encoder is writeLoop's, which runs once this returns.
			go c.control(func() error {
				c.henc.SetMaxDynamicTableSize(size)
				return nil
			})
		}
		return nil
	})
}

// control runs fn in writeLoop; false when the connection ended.
func (c *udpH2Conn) control(fn func() error) bool {
	select {
	case c.ctrl <- fn:
		return true
	case <-c.done:
		return false
	}
}

// fail ends the connection and every stream with err.
func (c *udpH2Conn) fail(err error) {
	c.failed.Do(func() {
		c.mu.Lock()
		c.err = err
		streams := make([]*udpH2Stream, 0, len(c.streams))
		for _, s := range c.streams {
			streams = append(streams, s)
		}
		c.streams = map[uint32]*udpH2Stream{}
		c.mu.Unlock()
		close(c.done)
		_ = c.conn.Close()
		for _, s := range streams {
			s.finish(err)
		}
	})
}

// usable reports whether the connection is alive and takes new streams.
func (c *udpH2Conn) usable() bool {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.err == nil && !c.draining && uint32(len(c.streams)+c.pendingOpens) < c.maxStreams
}

// ended reports whether the connection is gone.
func (c *udpH2Conn) ended() bool {
	select {
	case <-c.done:
		return true
	default:
		return false
	}
}

// keepAlive PINGs the server so that a connection the network stopped
// carrying is found, and closes the connection when nothing uses it.
func (c *udpH2Conn) keepAlive() {
	ticker := time.NewTicker(udpH2PingEvery)
	defer ticker.Stop()
	for {
		select {
		case <-c.done:
			return
		case <-ticker.C:
		}
		if since := time.Since(time.Unix(0, c.lastRead.Load())); since > udpH2DeadAfter && (c.uploading == nil || !c.uploading()) {
			logx.Debug("upstream UDP connection silent; closing it proxy=%s silent=%s", c.authority, since.Round(time.Second))
			c.fail(errUDPConnClosed)
			return
		}
		c.mu.Lock()
		idle := len(c.streams) == 0 && c.pendingOpens == 0
		quiet := time.Since(c.idleSince)
		draining := c.draining
		c.mu.Unlock()
		if idle && (draining || quiet > udpH2IdleClose) {
			logx.Debug("upstream UDP connection unused; closing it proxy=%s", c.authority)
			c.fail(errUDPConnClosed)
			return
		}
		c.control(func() error { return c.fr.WritePing(false, [8]byte{'u', 'd', 'p'}) })
	}
}

// writeLoop writes what control and writePacket queue, control frames
// first, flushing when nothing more waits.
func (c *udpH2Conn) writeLoop() {
	for {
		var err error
		select {
		case <-c.done:
			return
		case fn := <-c.ctrl:
			_ = c.conn.SetWriteDeadline(time.Now().Add(udpH2WriteTimeout))
			err = fn()
		case p := <-c.data:
			_ = c.conn.SetWriteDeadline(time.Now().Add(udpH2WriteTimeout))
			err = c.writeCapsule(p)
		}
		for more := true; more && err == nil; {
			select {
			case fn := <-c.ctrl:
				err = fn()
			default:
				select {
				case fn := <-c.ctrl:
					err = fn()
				case p := <-c.data:
					err = c.writeCapsule(p)
				default:
					more = false
				}
			}
		}
		if err == nil {
			err = c.bw.Flush()
		}
		if err != nil {
			c.fail(fmt.Errorf("%w: %w", errUDPConnClosed, err))
			return
		}
	}
}

// writeCapsule writes a queued packet as DATA frames, unless its stream ended
// meanwhile.
func (c *udpH2Conn) writeCapsule(p udpH2Packet) error {
	c.mu.Lock()
	c.queued -= len(p.capsule)
	maxFrame := int(c.maxFrameSize)
	c.mu.Unlock()
	if p.stream.stopped.Load() || p.stream.isDone() {
		return nil
	}
	id := p.stream.id.Load()
	for capsule := p.capsule; len(capsule) > 0; {
		n := min(len(capsule), maxFrame)
		if err := c.fr.WriteData(id, false, capsule[:n]); err != nil {
			return err
		}
		capsule = capsule[n:]
	}
	return nil
}

// writeHeaders starts a stream with its CONNECT-UDP request.
func (c *udpH2Conn) writeHeaders(s *udpH2Stream, token, host, port string) error {
	if s.isDone() {
		c.mu.Lock()
		c.pendingOpens--
		c.mu.Unlock()
		return nil
	}
	c.hbuf.Reset()
	enc := func(name, value string, sensitive bool) {
		_ = c.henc.WriteField(hpack.HeaderField{Name: name, Value: value, Sensitive: sensitive})
	}
	enc(":method", http.MethodConnect, false)
	enc(":protocol", "connect-udp", false)
	enc(":scheme", "https", false)
	enc(":authority", c.authority, false)
	enc(":path", connectUDPPath(host, port), false)
	enc("capsule-protocol", "?1", false)
	enc("proxy-authorization", "Bearer "+token, true)
	// As Firefox's CONNECT.
	enc("user-agent", controlplane.FirefoxUserAgent(), false)
	id := c.nextID
	c.nextID += 2
	c.mu.Lock()
	if c.nextID > 1<<30 {
		c.draining = true
	}
	c.pendingOpens--
	s.id.Store(id)
	c.streams[id] = s
	s.sendWindow = c.streamWindow
	c.mu.Unlock()
	return c.fr.WriteHeaders(http2.HeadersFrameParam{
		StreamID:      id,
		BlockFragment: c.hbuf.Bytes(),
		EndHeaders:    true,
	})
}

// readLoop handles what the server sends until the connection ends.
func (c *udpH2Conn) readLoop() {
	for {
		frame, err := c.fr.ReadFrame()
		if err != nil {
			c.fail(fmt.Errorf("%w: %w", errUDPConnClosed, err))
			return
		}
		c.lastRead.Store(time.Now().UnixNano())
		switch f := frame.(type) {
		case *http2.SettingsFrame:
			if f.IsAck() {
				continue
			}
			if err := c.applySettings(f); err != nil {
				c.fail(err)
				return
			}
			c.control(c.fr.WriteSettingsAck)
		case *http2.MetaHeadersFrame:
			if s := c.stream(f.StreamID); s != nil {
				s.gotHeaders(f)
			}
		case *http2.DataFrame:
			c.gotData(f)
		case *http2.WindowUpdateFrame:
			c.gotWindowUpdate(f)
		case *http2.PingFrame:
			if !f.IsAck() {
				data := f.Data
				c.control(func() error { return c.fr.WritePing(true, data) })
			}
		case *http2.RSTStreamFrame:
			if s := c.stream(f.StreamID); s != nil {
				s.stopped.Store(true)
				c.endStream(s, fmt.Errorf("%w: %s", errUDPStreamReset, f.ErrCode))
			}
		case *http2.GoAwayFrame:
			c.gotGoAway(f)
		}
	}
}

func (c *udpH2Conn) stream(id uint32) *udpH2Stream {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.streams[id]
}

// endStream ends s with err and removes it, resetting it toward the server
// unless the server reset it. A stream whose request was not written yet has no
// ID: writeHeaders then sees it ended and writes nothing.
func (c *udpH2Conn) endStream(s *udpH2Stream, err error) {
	s.finish(err)
	c.mu.Lock()
	id := s.id.Load()
	if id != 0 && c.streams[id] == s {
		delete(c.streams, id)
		if len(c.streams) == 0 {
			c.idleSince = time.Now()
		}
	}
	c.mu.Unlock()
	if id == 0 {
		return
	}
	c.control(func() error {
		if s.stopped.Swap(true) {
			return nil
		}
		return c.fr.WriteRSTStream(id, http2.ErrCodeCancel)
	})
}

// gotData gives a DATA frame's capsules to its stream and tops up the
// windows. A frame for a stream that ended still counts against the
// connection's window.
func (c *udpH2Conn) gotData(f *http2.DataFrame) {
	length := f.Length
	c.connUnacked += length
	if c.connUnacked >= udpH2WindowStep {
		n := c.connUnacked
		c.connUnacked = 0
		c.control(func() error { return c.fr.WriteWindowUpdate(0, n) })
	}
	s := c.stream(f.StreamID)
	if s == nil {
		return
	}
	if err := s.gotCapsuleData(f.Data()); err != nil {
		c.endStream(s, err)
		return
	}
	s.unacked += length
	if s.unacked >= udpH2WindowStep {
		n := s.unacked
		s.unacked = 0
		id := s.id.Load()
		c.control(func() error {
			if s.stopped.Load() {
				return nil
			}
			return c.fr.WriteWindowUpdate(id, n)
		})
	}
	if f.StreamEnded() {
		c.endStream(s, errUDPStreamEnded)
	}
}

func (c *udpH2Conn) gotWindowUpdate(f *http2.WindowUpdateFrame) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if f.StreamID == 0 {
		c.sendWindow += int64(f.Increment)
		return
	}
	if s := c.streams[f.StreamID]; s != nil {
		s.sendWindow += int64(f.Increment)
	}
}

// gotGoAway stops new streams, and ends the ones the server will not serve.
func (c *udpH2Conn) gotGoAway(f *http2.GoAwayFrame) {
	var gone []*udpH2Stream
	c.mu.Lock()
	c.draining = true
	for id, s := range c.streams {
		if id > f.LastStreamID {
			gone = append(gone, s)
		}
	}
	c.mu.Unlock()
	for _, s := range gone {
		c.endStream(s, fmt.Errorf("%w: %s", errUDPConnClosed, f.ErrCode))
	}
}

// open asks the proxy for a stream to host:port and waits for the answer.
func (c *udpH2Conn) open(ctx context.Context, token, host, port string) (*udpH2Stream, error) {
	c.mu.Lock()
	if c.err != nil {
		err := c.err
		c.mu.Unlock()
		return nil, err
	}
	if c.draining {
		c.mu.Unlock()
		return nil, errUDPConnClosed
	}
	c.pendingOpens++
	c.mu.Unlock()
	s := &udpH2Stream{
		c:      c,
		opened: make(chan error, 1),
		in:     make(chan []byte, udpH2ReadQueue),
		done:   make(chan struct{}),
	}
	if !c.control(func() error { return c.writeHeaders(s, token, host, port) }) {
		return nil, errUDPConnClosed
	}
	select {
	case err := <-s.opened:
		if err != nil {
			c.endStream(s, err)
			return nil, err
		}
		return s, nil
	case <-c.done:
		return nil, errUDPConnClosed
	case <-ctx.Done():
		c.endStream(s, ctx.Err())
		return nil, &tunnelOpenTimeoutError{timeout: udpH2OpenTimeout}
	}
}

// udpH2Stream is one CONNECT-UDP stream: packets to one destination and its
// replies.
type udpH2Stream struct {
	c *udpH2Conn
	// id is 0 until writeLoop writes the request.
	id atomic.Uint32
	// sendWindow is guarded by c.mu.
	sendWindow int64
	// stopped: no more frames for this stream.
	stopped atomic.Bool
	// capsules holds a capsule still incomplete, unacked what the window was
	// not topped up for; readLoop's alone.
	capsules []byte
	unacked  uint32

	opened chan error
	in     chan []byte
	done   chan struct{}
	once   sync.Once
	err    error
	// traffic, when set, counts the packets' bytes.
	traffic func(int)
}

func (s *udpH2Stream) isDone() bool {
	select {
	case <-s.done:
		return true
	default:
		return false
	}
}

// finish ends the stream with err; a wait for the answer ends too.
func (s *udpH2Stream) finish(err error) {
	s.once.Do(func() {
		s.err = err
		close(s.done)
		select {
		case s.opened <- err:
		default:
		}
	})
}

// gotHeaders is the answer to the request (a later block is ignored).
func (s *udpH2Stream) gotHeaders(f *http2.MetaHeadersFrame) {
	status, err := strconv.Atoi(f.PseudoValue("status"))
	if err != nil {
		s.c.endStream(s, fmt.Errorf("the proxy's answer has no status: %w", err))
		return
	}
	switch {
	case status >= 200 && status < 300:
		select {
		case s.opened <- nil:
		default:
		}
	case status >= 100 && status < 200:
	default:
		e := &proxyConnectHTTPError{statusCode: status, status: strconv.Itoa(status) + " " + http.StatusText(status)}
		for _, field := range f.RegularFields() {
			if field.Name == "proxy-status" {
				e.body = field.Value
			}
		}
		s.c.endStream(s, e)
		return
	}
	if f.StreamEnded() {
		s.c.endStream(s, errUDPStreamEnded)
	}
}

// gotCapsuleData takes the bytes of a DATA frame: whole DATAGRAM capsules go
// to the reader, the rest waits for the next frame. Other capsule types are
// skipped, as RFC 9297 asks; a capsule too large to be a packet is an error.
func (s *udpH2Stream) gotCapsuleData(data []byte) error {
	buf := data
	if len(s.capsules) > 0 {
		s.capsules = append(s.capsules, data...)
		buf = s.capsules
	}
	for {
		kind, n1 := quicVarint(buf)
		if n1 == 0 {
			break
		}
		size, n2 := quicVarint(buf[n1:])
		if n2 == 0 {
			break
		}
		if size > udpH2MaxCapsule {
			return fmt.Errorf("a capsule of %d bytes from the proxy", size)
		}
		end := n1 + n2 + int(size)
		if end > len(buf) {
			break
		}
		if kind == 0 {
			s.gotDatagram(buf[n1+n2 : end])
		}
		buf = buf[end:]
	}
	// What is left waits; copied, as the framer reuses its buffer.
	s.capsules = append(s.capsules[:0], buf...)
	return nil
}

// gotDatagram queues a packet for the reader, or drops it when the reader is
// behind.
func (s *udpH2Stream) gotDatagram(payload []byte) {
	id, n := quicVarint(payload)
	if n == 0 || id != 0 {
		return
	}
	packet := append([]byte(nil), payload[n:]...)
	select {
	case s.in <- packet:
	default:
	}
}

// ReadPacket returns the next packet from the destination.
func (s *udpH2Stream) ReadPacket(p []byte) (int, error) {
	select {
	case packet := <-s.in:
		return s.deliver(p, packet), nil
	default:
	}
	select {
	case packet := <-s.in:
		return s.deliver(p, packet), nil
	case <-s.done:
		return 0, s.err
	}
}

func (s *udpH2Stream) deliver(p, packet []byte) int {
	n := copy(p, packet)
	if s.traffic != nil {
		s.traffic(n)
	}
	return n
}

// WritePacket sends p to the destination. It does not wait: a packet the
// connection cannot take now (its flow-control window or its queue is full)
// is dropped, like a packet a full router drops. The error is only for a
// stream that ended.
func (s *udpH2Stream) WritePacket(p []byte) error {
	if s.isDone() {
		return s.err
	}
	capsule := appendQUICVarint(make([]byte, 0, len(p)+8), 0)
	capsule = appendQUICVarint(capsule, uint64(len(p)+1))
	capsule = append(capsule, 0)
	capsule = append(capsule, p...)

	c := s.c
	c.mu.Lock()
	size := len(capsule)
	if c.err != nil || c.queued+size > udpH2MaxQueued || c.sendWindow < int64(size) || s.sendWindow < int64(size) {
		c.mu.Unlock()
		return nil
	}
	select {
	case c.data <- udpH2Packet{stream: s, capsule: capsule}:
		c.queued += size
		c.sendWindow -= int64(size)
		s.sendWindow -= int64(size)
	default:
	}
	c.mu.Unlock()
	if s.traffic != nil {
		s.traffic(len(p))
	}
	return nil
}

// Close ends the stream.
func (s *udpH2Stream) Close() error {
	s.c.endStream(s, net.ErrClosed)
	return nil
}

// quicVarint reads a QUIC variable-length integer (RFC 9000 16) from b, and
// how many bytes it took; 0 when b is too short.
func quicVarint(b []byte) (uint64, int) {
	if len(b) == 0 {
		return 0, 0
	}
	length := 1 << (b[0] >> 6)
	if len(b) < length {
		return 0, 0
	}
	v := uint64(b[0] & 0x3f)
	for _, next := range b[1:length] {
		v = v<<8 | uint64(next)
	}
	return v, length
}

// appendQUICVarint appends v as a QUIC variable-length integer.
func appendQUICVarint(b []byte, v uint64) []byte {
	switch {
	case v < 1<<6:
		return append(b, byte(v))
	case v < 1<<14:
		return append(b, byte(v>>8)|0x40, byte(v))
	case v < 1<<30:
		return append(b, byte(v>>24)|0x80, byte(v>>16), byte(v>>8), byte(v))
	}
	return append(b, byte(v>>56)|0xc0, byte(v>>48), byte(v>>40), byte(v>>32), byte(v>>24), byte(v>>16), byte(v>>8), byte(v))
}

// connectUDPPath is the path of a CONNECT-UDP request to host:port (RFC 9298
// 2.1, the default template): an IPv6 address has its colons encoded.
func connectUDPPath(host, port string) string {
	return "/.well-known/masque/udp/" + pathSegment(host) + "/" + pathSegment(port) + "/"
}

// pathSegment percent-encodes all but RFC 3986's unreserved characters.
func pathSegment(s string) string {
	const hex = "0123456789ABCDEF"
	var b []byte
	for i := 0; i < len(s); i++ {
		c := s[i]
		switch {
		case 'a' <= c && c <= 'z', 'A' <= c && c <= 'Z', '0' <= c && c <= '9', c == '-', c == '.', c == '_', c == '~':
			b = append(b, c)
		default:
			b = append(b, '%', hex[c>>4], hex[c&15])
		}
	}
	return string(b)
}
