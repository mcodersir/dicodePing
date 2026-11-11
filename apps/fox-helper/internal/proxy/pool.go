package proxy

import (
	"fmt"
	"hash/fnv"
	"net"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"dicodeping/fox/internal/logx"
)

const (
	upstreamSessionHealthInterval = 500 * time.Millisecond
	upstreamSessionRetryDelay = 10 * time.Second // upper bound, not the first delay
)

// Quick initial retries cover a short route transition; sustained failures
// still back off to avoid hammering the endpoint. Slots are staggered.
func poolRetryDelay(attempt, slot int) time.Duration {
	delay := 500 * time.Millisecond
	for i := 1; i < attempt && delay < upstreamSessionRetryDelay; i++ {
		delay *= 2
	}
	delay += time.Duration(slot % 5) * 37 * time.Millisecond
	if delay > upstreamSessionRetryDelay {
		return upstreamSessionRetryDelay
	}
	return delay
}

type pooledProxySession struct {
	mu      sync.Mutex
	session proxySession
	healthy bool
	retired bool
	refs    int
}

type proxySessionPool struct {
	create         func() (proxySession, error)
	setCreateToken func(string)
	sessions       []*pooledProxySession
	clientSlots    map[string]int
	next           atomic.Uint64
	tokenMu        sync.RWMutex
	currentToken   string

	mu        sync.Mutex
	closed    bool
	done      chan struct{}
	closeOnce sync.Once
}

func newProxySessionPool(size int, create func() (proxySession, error), setCreateToken ...func(string)) (*proxySessionPool, error) {
	if size < 1 {
		return nil, fmt.Errorf("upstream session pool size must be at least 1")
	}

	pool := &proxySessionPool{
		create:      create,
		sessions:    make([]*pooledProxySession, size),
		clientSlots: make(map[string]int),
		done:        make(chan struct{}),
	}
	if len(setCreateToken) > 0 {
		pool.setCreateToken = setCreateToken[0]
	}
	successes := 0
	var firstErr error
	for i := 0; i < size; i++ {
		session, err := create()
		if err != nil {
			if firstErr == nil {
				firstErr = err
			}
			logx.Warn("creating upstream session failed slot=%d size=%d err=%s", i+1, size, logx.Err(err))
			continue
		}
		pool.sessions[i] = newPooledProxySession(session)
		successes++
	}
	if successes == 0 {
		_ = pool.Close()
		return nil, fmt.Errorf("creating upstream session pool: %w", firstErr)
	}
	if successes < size {
		logx.Warn("upstream proxy session pool partially established available=%d desired=%d affinity=client-ip failover=enabled", successes, size)
		for i := range pool.sessions {
			if pool.sessions[i] == nil {
				go pool.replenishSlot(i)
			}
		}
	} else {
		logx.Info("upstream proxy session pool established size=%d affinity=client-ip failover=enabled", successes)
	}
	go pool.watchHealth()
	return pool, nil
}

// Keep the warm standby pool warm after keepalive has detected a dead socket,
// even while clients wait before retrying. This only reads liveness state: it
// sends no probes, opens no extra slots and leaves live streams untouched.
func (p *proxySessionPool) watchHealth() {
	ticker := time.NewTicker(upstreamSessionHealthInterval)
	defer ticker.Stop()
	for {
		select {
		case <-p.done:
			return
		case <-ticker.C:
			for i := range p.sessions {
				pooled := p.slot(i)
				if pooled == nil {
					continue
				}
				pooled.mu.Lock()
				dead := !pooled.retired && pooled.session != nil && !isSessionAlive(pooled.session)
				if dead {
					pooled.healthy = false
				}
				pooled.mu.Unlock()
				if dead {
					p.retireSlot(i, pooled)
				}
			}
		}
	}
}

func newPooledProxySession(session proxySession) *pooledProxySession {
	return &pooledProxySession{
		session: session,
		healthy: true,
	}
}

func (p *proxySessionPool) OpenTunnel(authority string) (net.Conn, error) {
	return p.openTunnel(authority, "")
}

func (p *proxySessionPool) OpenTunnelForClient(authority, clientKey string) (net.Conn, error) {
	return p.openTunnel(authority, clientKey)
}

func (p *proxySessionPool) UpdateToken(token string) error {
	if strings.TrimSpace(token) == "" {
		return fmt.Errorf("empty proxy session token")
	}
	if p == nil {
		return ErrNoUsableSession
	}
	p.tokenMu.Lock()
	p.currentToken = token
	p.tokenMu.Unlock()
	if p.setCreateToken != nil {
		p.setCreateToken(token)
	}

	p.mu.Lock()
	sessions := append([]*pooledProxySession(nil), p.sessions...)
	p.mu.Unlock()
	updated := 0
	for _, pooled := range sessions {
		if pooled == nil {
			continue
		}
		session, ok := pooled.acquire()
		if !ok {
			continue
		}
		updater, ok := session.(proxySessionTokenUpdater)
		if !ok {
			pooled.release()
			return fmt.Errorf("upstream session does not support token update")
		}
		if err := updater.UpdateToken(token); err != nil {
			pooled.release()
			return err
		}
		pooled.release()
		updated++
	}
	if updated == 0 {
		return ErrNoUsableSession
	}
	return nil
}

func (p *proxySessionPool) applyCurrentToken(session proxySession) error {
	p.tokenMu.RLock()
	token := p.currentToken
	p.tokenMu.RUnlock()
	if token == "" {
		return nil
	}
	updater, ok := session.(proxySessionTokenUpdater)
	if !ok {
		return fmt.Errorf("upstream session does not support token update")
	}
	return updater.UpdateToken(token)
}

func (p *proxySessionPool) openTunnel(authority, clientKey string) (net.Conn, error) {
	if p == nil || len(p.sessions) == 0 {
		return nil, ErrNoUsableSession
	}

	start := p.nextSlot(clientKey)
	var lastErr error
	for i := 0; i < len(p.sessions); i++ {
		slot := (start + i) % len(p.sessions)
		pooled := p.slot(slot)
		if pooled == nil {
			continue
		}
		session, ok := pooled.acquire()
		if !ok {
			// A slot the keepalive marked unhealthy stays skipped until it is
			// retired, so retire it here to trigger background replenishment.
			if pooled.needsRetire() {
				p.setClientFallback(clientKey, start, slot, (slot+1)%len(p.sessions))
				p.retireSlot(slot, pooled)
			}
			continue
		}
		conn, err := session.OpenTunnel(authority)
		if err == nil {
			p.rememberClientSlot(clientKey, start, slot)
			return &pooledTunnelConn{
				Conn:    conn,
				release: pooled.release,
			}, nil
		}
		pooled.release()
		lastErr = err
		if !shouldRebuildProxySession(err) {
			return nil, err
		}
		p.setClientFallback(clientKey, start, slot, (slot+1)%len(p.sessions))
		p.retireSlot(slot, pooled)
	}
	if lastErr != nil {
		return nil, lastErr
	}
	return nil, ErrNoUsableSession
}

func (p *proxySessionPool) nextSlot(clientKey string) int {
	if clientKey == "" {
		return int((p.next.Add(1) - 1) % uint64(len(p.sessions)))
	}

	p.mu.Lock()
	if slot, ok := p.clientSlots[clientKey]; ok {
		p.mu.Unlock()
		return slot
	}
	h := fnv.New32a()
	_, _ = h.Write([]byte(clientKey))
	slot := int(h.Sum32() % uint32(len(p.sessions)))
	p.clientSlots[clientKey] = slot
	p.mu.Unlock()
	return slot
}

func (p *proxySessionPool) rememberClientSlot(clientKey string, initialSlot, actualSlot int) {
	if clientKey == "" || initialSlot == actualSlot {
		return
	}
	p.mu.Lock()
	currentSlot, ok := p.clientSlots[clientKey]
	if !p.closed && ok && (currentSlot == initialSlot || p.sessions[currentSlot] == nil) {
		p.clientSlots[clientKey] = actualSlot
	}
	p.mu.Unlock()
}

func (p *proxySessionPool) setClientFallback(clientKey string, initialSlot, failedSlot, fallbackSlot int) {
	if clientKey == "" {
		return
	}
	p.mu.Lock()
	currentSlot, ok := p.clientSlots[clientKey]
	if !p.closed && ok && (currentSlot == initialSlot || currentSlot == failedSlot || p.sessions[currentSlot] == nil) {
		p.clientSlots[clientKey] = fallbackSlot
	}
	p.mu.Unlock()
}

func (p *proxySessionPool) Close() error {
	if p == nil {
		return nil
	}
	var sessions []*pooledProxySession
	p.closeOnce.Do(func() {
		close(p.done)
		p.mu.Lock()
		p.closed = true
		sessions = append(sessions, p.sessions...)
		for i := range p.sessions {
			p.sessions[i] = nil
		}
		p.mu.Unlock()
	})
	var err error
	for _, pooled := range sessions {
		if pooled == nil {
			continue
		}
		if closeErr := pooled.closeNow(); err == nil {
			err = closeErr
		}
	}
	return err
}

func (p *proxySessionPool) slot(i int) *pooledProxySession {
	p.mu.Lock()
	defer p.mu.Unlock()
	if p.closed || i < 0 || i >= len(p.sessions) {
		return nil
	}
	return p.sessions[i]
}

func (p *proxySessionPool) retireSlot(i int, expected *pooledProxySession) {
	expected.retire()

	p.mu.Lock()
	if p.closed || i < 0 || i >= len(p.sessions) || p.sessions[i] != expected {
		p.mu.Unlock()
		return
	}
	p.sessions[i] = nil
	p.mu.Unlock()

	go p.replenishSlot(i)
}

func (p *proxySessionPool) replenishSlot(i int) {
	started := time.Now()
	attempts := 0
	for {
		p.mu.Lock()
		if p.closed || i < 0 || i >= len(p.sessions) || p.sessions[i] != nil {
			p.mu.Unlock()
			return
		}
		p.mu.Unlock()

		attempts++
		session, err := p.create()
		if err != nil {
			logx.Warn("replenishing upstream session failed slot=%d err=%s", i+1, logx.Err(err))
			if !p.waitOrClosed(poolRetryDelay(attempts, i)) {
				return
			}
			continue
		}
		if err := p.applyCurrentToken(session); err != nil {
			_ = session.Close()
			logx.Warn("applying renewed token to replenished upstream session failed slot=%d err=%s", i+1, logx.Err(err))
			if !p.waitOrClosed(poolRetryDelay(attempts, i)) {
				return
			}
			continue
		}

		pooled := newPooledProxySession(session)
		p.mu.Lock()
		if p.closed || p.sessions[i] != nil {
			p.mu.Unlock()
			_ = pooled.closeNow()
			return
		}
		p.sessions[i] = pooled
		p.mu.Unlock()
		logx.Info("upstream proxy session replenished slot=%d attempts=%d recovery_ms=%d", i+1, attempts, time.Since(started).Milliseconds())
		return
	}
}

func (p *proxySessionPool) waitOrClosed(d time.Duration) bool {
	timer := time.NewTimer(d)
	defer timer.Stop()
	select {
	case <-timer.C:
		return true
	case <-p.done:
		return false
	}
}

func (p *pooledProxySession) acquire() (proxySession, bool) {
	p.mu.Lock()
	defer p.mu.Unlock()
	if !p.healthy || p.retired || p.session == nil {
		return nil, false
	}
	if !isSessionAlive(p.session) {
		// The keepalive already saw this connection die. Mark it unhealthy so
		// openTunnel retires the slot and replenishes it in the background.
		p.healthy = false
		return nil, false
	}
	p.refs++
	return p.session, true
}

// needsRetire reports whether this slot holds a session that is unusable but
// has not been retired yet, so the caller can start a replacement.
func (p *pooledProxySession) needsRetire() bool {
	p.mu.Lock()
	defer p.mu.Unlock()
	return !p.retired && !p.healthy
}

func (p *pooledProxySession) release() {
	session := p.releaseLocked()
	if session != nil {
		_ = session.Close()
	}
}

func (p *pooledProxySession) releaseLocked() proxySession {
	p.mu.Lock()
	defer p.mu.Unlock()
	if p.refs > 0 {
		p.refs--
	}
	if p.refs == 0 && p.retired && p.session != nil {
		session := p.session
		p.session = nil
		return session
	}
	return nil
}

func (p *pooledProxySession) retire() {
	p.mu.Lock()
	p.healthy = false
	p.retired = true
	shouldClose := p.refs == 0 && p.session != nil
	var session proxySession
	if shouldClose {
		session = p.session
		p.session = nil
	}
	p.mu.Unlock()
	if session != nil {
		_ = session.Close()
	}
}

func (p *pooledProxySession) closeNow() error {
	p.mu.Lock()
	session := p.session
	p.session = nil
	p.healthy = false
	p.retired = true
	p.mu.Unlock()
	if session == nil {
		return nil
	}
	return session.Close()
}

type pooledTunnelConn struct {
	net.Conn
	release func()
	once    sync.Once
}

func (c *pooledTunnelConn) Close() error {
	var err error
	c.once.Do(func() {
		err = c.Conn.Close()
		if c.release != nil {
			c.release()
		}
	})
	return err
}

func (c *pooledTunnelConn) CloseRead() error {
	if closeReader, ok := c.Conn.(interface{ CloseRead() error }); ok {
		return closeReader.CloseRead()
	}
	return nil
}

func (c *pooledTunnelConn) CloseWrite() error {
	if closeWriter, ok := c.Conn.(interface{ CloseWrite() error }); ok {
		return closeWriter.CloseWrite()
	}
	return nil
}
