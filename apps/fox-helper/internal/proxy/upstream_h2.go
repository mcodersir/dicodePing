package proxy

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"golang.org/x/net/http2"

	"dicodeping/fox/internal/controlplane"
	"dicodeping/fox/internal/logx"
)

// The keepalive PINGs the connection this often and waits this long for
// the answer: a connection the network stopped carrying (some cut the
// connection to a server every minute or so) is found within about 15
// seconds, while the tunnels on it wait. Tests shorten them.
var (
	upstreamKeepAliveInterval    = 5 * time.Second
	upstreamKeepAlivePingTimeout = 5 * time.Second
)

const (
	// upstreamKeepAliveMisses is how many PINGs in a row must go
	// unanswered before the session counts as dead. A PING that waits
	// behind a video's data on a busy phone link is no miss: data arriving
	// meanwhile shows the connection alive (watchedConn).
	upstreamKeepAliveMisses = 2
	// An upload fills the link's queue, and the answer to a PING behind it
	// may take many seconds while nothing arrives. upstreamBusyWrite is how
	// much must have left since data last arrived to think so, and
	// upstreamBusyGrace how long that may go on, for a connection that died
	// during an upload.
	upstreamBusyWrite = 256 << 10
	upstreamBusyGrace = 45 * time.Second
	// upstreamStreamWindow is how much a server may send on one tunnel ahead of
	// what arrived here. Every tunnel shares one connection, so the answer to a
	// new one comes behind all of it: the default 4 MiB makes a new connection
	// wait seconds beside a download (SESSIONS.md). One tunnel's speed is at most
	// this per round trip. Several tunnels add up: the connection's window stays
	// large, since a client that stopped reading holds on to its share of it.
	upstreamStreamWindow = 1 << 20
)

var errProxyHTTP2Unavailable = errors.New("proxy did not negotiate HTTP/2")

type h2ProxySession struct {
	raw       net.Conn
	cc        *http2.ClientConn
	watched   *watchedConn
	opened    time.Time
	proxyHost string
	token     string
	timeout   time.Duration
	tokenMu   sync.RWMutex
	health    sessionFailureTracker
	closeOnce sync.Once
	closeErr  error

	// alive is cleared once a keepalive PING fails or the session is closed,
	// so the pool can skip it before binding a client connection to it.
	alive atomic.Bool
	// stopKeepAlive stops the keepalive goroutine on Close.
	stopKeepAlive context.CancelFunc
}

func newH2ProxySession(proxyURL *url.URL, token string, timeout time.Duration) (*h2ProxySession, error) {
	session, err := dialH2ProxySession(proxyURL, token, timeout)
	if err != nil {
		return nil, err
	}
	logx.Info("upstream HTTP/2 session established proxy=%s", session.proxyHost)
	return session, nil
}

// dialH2ProxySession establishes an HTTP/2 session without logging it; the
// latency measurement opens one per location.
func dialH2ProxySession(proxyURL *url.URL, token string, timeout time.Duration) (*h2ProxySession, error) {
	proxyHost := proxyURL.Host
	if proxyURL.Port() == "" {
		proxyHost = proxyURL.Hostname() + ":443"
	}

	// The timeout covers resolving, connecting, and the TLS handshake, as
	// tls.DialWithDialer did.
	dialCtx, cancelDial := context.Background(), context.CancelFunc(func() {})
	if timeout > 0 {
		dialCtx, cancelDial = context.WithTimeout(context.Background(), timeout)
	}
	defer cancelDial()
	proxyTLS, raw, err := dialUpstreamTLS(dialCtx, proxyURL, proxyHost)
	if err != nil {
		return nil, err
	}

	transport, err := newUpstreamH2Transport()
	if err != nil {
		_ = proxyTLS.Close()
		return nil, err
	}
	cc, err := transport.NewClientConn(proxyTLS)
	if err != nil {
		_ = proxyTLS.Close()
		return nil, err
	}

	ctx, cancel := context.WithCancel(context.Background())
	session := &h2ProxySession{
		raw:           proxyTLS,
		cc:            cc,
		watched:       raw,
		opened:        time.Now(),
		proxyHost:     proxyHost,
		token:         token,
		timeout:       timeout,
		stopKeepAlive: cancel,
	}
	session.alive.Store(true)
	go session.runKeepAlive(ctx)

	return session, nil
}

// newUpstreamH2Transport is the HTTP/2 client of a session to Mozilla.
func newUpstreamH2Transport() (*http2.Transport, error) {
	transport, err := http2.ConfigureTransports(&http.Transport{
		HTTP2: &http.HTTP2Config{MaxReceiveBufferPerStream: upstreamStreamWindow},
	})
	if err != nil {
		return nil, err
	}
	// A new tunnel waits for a free stream when the server's
	// MAX_CONCURRENT_STREAMS is reached, rather than failing as if the
	// connection were gone.
	transport.StrictMaxConcurrentStreams = true
	transport.ReadIdleTimeout = 30 * time.Second
	transport.PingTimeout = 15 * time.Second
	transport.WriteByteTimeout = 30 * time.Second
	return transport, nil
}

// runKeepAlive pings the upstream connection periodically so a silently
// dropped session is noticed while idle, rather than when a client next tries
// to open a tunnel through it.
func (s *h2ProxySession) runKeepAlive(ctx context.Context) {
	ticker := time.NewTicker(upstreamKeepAliveInterval)
	defer ticker.Stop()

	misses := 0
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			sent := time.Now()
			pingCtx, cancel := context.WithTimeout(ctx, upstreamKeepAlivePingTimeout)
			err := s.cc.Ping(pingCtx)
			cancel()
			if err == nil {
				misses = 0
				continue
			}
			if ctx.Err() != nil {
				return
			}
			closed := s.cc.State().Closed
			if !closed && (s.watched.readSince(sent) || s.watched.uploading()) {
				// Busy, not dead: data came while the PING waited, or it
				// waits behind an upload.
				misses = 0
				continue
			}
			if misses++; misses < upstreamKeepAliveMisses && !closed {
				logx.Debug("upstream HTTP/2 keepalive PING unanswered proxy=%s misses=%d err=%s", s.proxyHost, misses, logx.Err(err))
				continue
			}
			s.alive.Store(false)
			reportConnectionLost(s.proxyHost, s.watched.RemoteAddr(), time.Since(s.opened), s.cc.State().StreamsActive, s.watched.failure(), err)
			// The tunnels waiting on the dead connection fail now and
			// are retried on a new session, instead of waiting out
			// their CONNECT timeout.
			_ = s.cc.Close()
			return
		}
	}
}

// IsAlive reports whether this session can still carry new tunnels. A
// session whose streams are all in use is busy, not dead: new tunnels wait
// for a free stream (StrictMaxConcurrentStreams). A connection closing after
// a GOAWAY may still look alive here; its next open fails and the session is
// rebuilt then.
func (s *h2ProxySession) IsAlive() bool {
	if !s.alive.Load() {
		return false
	}
	st := s.cc.State()
	return !st.Closed && !st.Closing
}

// saturated reports whether every stream the server allows is in use or
// waited for, so a new tunnel has to wait for one to end.
func (s *h2ProxySession) saturated() bool {
	st := s.cc.State()
	return st.MaxConcurrentStreams > 0 && st.StreamsActive+st.StreamsReserved+st.StreamsPending >= int(st.MaxConcurrentStreams)
}

// saturatedOpenWait bounds how long a new tunnel waits for a free stream on
// a session whose streams are all in use.
const saturatedOpenWait = 10 * time.Second

// errSessionSaturated is a tunnel that found no free stream in time. The
// session is busy, not broken: it is neither counted against its health nor
// rebuilt (which would fetch a new pass for nothing).
var errSessionSaturated = errors.New("upstream session has no free stream")

func (s *h2ProxySession) OpenTunnel(authority string) (net.Conn, error) {
	reqBody := newTunnelWriteBuffer(defaultTunnelWriteBufSize)
	busy := s.saturated()
	timeout := s.timeout
	if busy && (timeout <= 0 || timeout > saturatedOpenWait) {
		timeout = saturatedOpenWait
	}
	resp, cancel, err := roundTripWithOpenTimeout(timeout, func(ctx context.Context) (*http.Response, error) {
		req, err := http.NewRequestWithContext(ctx, http.MethodConnect, "http://"+authority, reqBody)
		if err != nil {
			return nil, err
		}
		req.Host = authority
		req.URL.Host = s.proxyHost
		req.Header.Set("Proxy-Authorization", "Bearer "+s.bearerToken())
		// As Firefox's CONNECT; Go would otherwise name itself.
		req.Header.Set("User-Agent", controlplane.FirefoxUserAgent())
		return s.cc.RoundTrip(req)
	})
	if err != nil {
		reqBody.failRead(io.ErrClosedPipe)
		var timeoutErr *tunnelOpenTimeoutError
		if busy && errors.As(err, &timeoutErr) {
			return nil, fmt.Errorf("%w: %w", errSessionSaturated, err)
		}
		return nil, s.health.observe(authority, err)
	}
	if resp.StatusCode < 200 || resp.StatusCode > 299 {
		cancel()
		body, _ := io.ReadAll(io.LimitReader(resp.Body, 2048))
		_ = resp.Body.Close()
		reqBody.failRead(io.ErrClosedPipe)
		return nil, s.health.observe(authority, &proxyConnectHTTPError{
			statusCode: resp.StatusCode,
			status:     resp.Status,
			body:       strings.TrimSpace(string(body)),
		})
	}
	s.health.observe(authority, nil)

	return &tunnelConn{
		reader:  resp.Body,
		writer:  reqBody,
		reqBody: reqBody,
		name:    "h2-connect-stream",
		cancel:  cancel,
	}, nil
}

func (s *h2ProxySession) bearerToken() string {
	s.tokenMu.RLock()
	defer s.tokenMu.RUnlock()
	return s.token
}

func (s *h2ProxySession) UpdateToken(token string) error {
	if strings.TrimSpace(token) == "" {
		return fmt.Errorf("empty proxy session token")
	}
	s.tokenMu.Lock()
	s.token = token
	s.tokenMu.Unlock()
	return nil
}

func (s *h2ProxySession) Close() error {
	s.closeOnce.Do(func() {
		s.alive.Store(false)
		if s.stopKeepAlive != nil {
			s.stopKeepAlive()
		}
		if s.cc != nil {
			s.closeErr = s.cc.Close()
		}
		if s.raw != nil {
			if closeErr := s.raw.Close(); s.closeErr == nil {
				s.closeErr = closeErr
			}
		}
	})
	return s.closeErr
}
