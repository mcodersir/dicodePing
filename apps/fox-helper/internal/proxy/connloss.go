package proxy

import (
	"errors"
	"io"
	"net"
	"strings"
	"sync"
	"sync/atomic"
	"syscall"
	"time"

	"dicodeping/fox/internal/logx"
)

// watchedConn is the TCP connection under an upstream session's TLS. It
// notes when data last arrived and how much left, so the keepalive can tell
// a busy connection from a dead one, and the first error, which says how the
// connection ended.
type watchedConn struct {
	net.Conn
	lastRead atomic.Int64 // UnixNano of the last read that returned data
	written  atomic.Int64 // bytes the system took
	// writtenAtRead is written when data last arrived.
	writtenAtRead atomic.Int64
	errOnce       sync.Once
	err           atomic.Pointer[error]
}

func newWatchedConn(conn net.Conn) *watchedConn {
	return &watchedConn{Conn: conn}
}

func (c *watchedConn) Read(p []byte) (int, error) {
	n, err := c.Conn.Read(p)
	if n > 0 {
		c.lastRead.Store(time.Now().UnixNano())
		c.writtenAtRead.Store(c.written.Load())
	}
	c.fail(err)
	return n, err
}

func (c *watchedConn) Write(p []byte) (int, error) {
	n, err := c.Conn.Write(p)
	c.written.Add(int64(n))
	c.fail(err)
	return n, err
}

func (c *watchedConn) fail(err error) {
	if err != nil {
		c.errOnce.Do(func() { c.err.Store(&err) })
	}
}

// readSince reports whether data arrived at t or after.
func (c *watchedConn) readSince(t time.Time) bool {
	return c.lastRead.Load() >= t.UnixNano()
}

// uploading reports whether an upload may be why nothing arrives: much left
// since data last arrived, and that was not too long ago.
func (c *watchedConn) uploading() bool {
	return c.written.Load()-c.writtenAtRead.Load() >= upstreamBusyWrite &&
		time.Since(time.Unix(0, c.lastRead.Load())) < upstreamBusyGrace
}

// failure is the connection's first read or write error, nil while none.
func (c *watchedConn) failure() error {
	if err := c.err.Load(); err != nil {
		return *err
	}
	return nil
}

// connLossWindow is how far back reportConnectionLost counts the losses of
// a server's connection, and connLossPattern how many losses within it,
// after a short life each (connShortLife on average), show a network that
// keeps cutting the connection rather than a one-off drop.
const (
	connLossWindow  = 10 * time.Minute // the log's lost_in_10m
	connLossPattern = 3
	connShortLife   = 3 * time.Minute
)

var connLosses struct {
	sync.Mutex
	// lives maps a server IP to the lives of its connections lost within
	// connLossWindow, by the time they were lost.
	lives map[string][]connLoss
}

type connLoss struct {
	at    time.Time
	lived time.Duration
}

// reportConnectionLost logs, in one line, that the upstream connection to
// proxyHost (at remote) ended after lived with tunnels open: why
// (lossReason), and, when it keeps happening, how often and how soon,
// which tells a network that cuts the connection from a server that
// failed.
func reportConnectionLost(proxyHost string, remote net.Addr, lived time.Duration, tunnels int, connErr, pingErr error) {
	ip := remoteIP(remote)
	now := time.Now()
	connLosses.Lock()
	if connLosses.lives == nil {
		connLosses.lives = make(map[string][]connLoss)
	}
	recent := connLosses.lives[ip][:0]
	for _, l := range connLosses.lives[ip] {
		if now.Sub(l.at) < connLossWindow {
			recent = append(recent, l)
		}
	}
	recent = append(recent, connLoss{at: now, lived: lived})
	connLosses.lives[ip] = recent
	var total time.Duration
	for _, l := range recent {
		total += l.lived
	}
	connLosses.Unlock()
	average := total / time.Duration(len(recent))

	err := connErr
	if err == nil {
		err = pingErr
	}
	reason := lossReason(connErr)
	if len(recent) >= connLossPattern && average < connShortLife {
		logx.Warn("upstream connection lost again: the network keeps cutting the connection to this server proxy=%s ip=%s after=%s reason=%q tunnels=%d lost_in_10m=%d average_life=%s err=%s",
			proxyHost, ip, lived.Round(time.Second), reason, tunnels, len(recent), average.Round(time.Second), logx.Err(err))
		return
	}
	logx.Warn("upstream connection lost proxy=%s ip=%s after=%s reason=%q tunnels=%d err=%s",
		proxyHost, ip, lived.Round(time.Second), reason, tunnels, logx.Err(err))
}

// lossReason says in a few words how a connection ended, from its first
// read or write error (nil: the keepalive's PINGs went unanswered while
// nothing failed, as when the network stops carrying the connection).
func lossReason(err error) string {
	var netErr net.Error
	text := ""
	if err != nil {
		text = strings.ToLower(err.Error())
	}
	switch {
	case err == nil:
		return "no answer from the network"
	case errors.Is(err, io.EOF), errors.Is(err, io.ErrUnexpectedEOF):
		return "closed by the other side"
	case errors.Is(err, syscall.ECONNRESET), errors.Is(err, syscall.ECONNABORTED), errors.Is(err, syscall.EPIPE),
		strings.Contains(text, "forcibly closed"), strings.Contains(text, "connection reset"),
		strings.Contains(text, "broken pipe"), strings.Contains(text, "aborted"):
		return "cut off (reset)"
	case errors.As(err, &netErr) && netErr.Timeout(),
		strings.Contains(text, "did not properly respond"), strings.Contains(text, "timed out"):
		return "no answer from the network"
	}
	return "failed"
}

func remoteIP(addr net.Addr) string {
	if addr == nil {
		return "unknown"
	}
	if tcp, ok := addr.(*net.TCPAddr); ok {
		return tcp.IP.String()
	}
	if host, _, err := net.SplitHostPort(addr.String()); err == nil {
		return host
	}
	return addr.String()
}
