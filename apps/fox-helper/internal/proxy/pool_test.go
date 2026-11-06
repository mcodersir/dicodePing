package proxy

import (
	"errors"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

func TestProxySessionPoolDistributesTunnels(t *testing.T) {
	t.Parallel()

	sessions := []*fakeProxySession{{}, {}, {}}
	var created atomic.Int32
	pool, err := newProxySessionPool(len(sessions), func() (proxySession, error) {
		idx := int(created.Add(1)) - 1
		return sessions[idx], nil
	})
	if err != nil {
		t.Fatalf("newProxySessionPool returned error: %v", err)
	}
	defer pool.Close()

	for i := 0; i < 6; i++ {
		conn, err := pool.OpenTunnel("example.com:443")
		if err != nil {
			t.Fatalf("OpenTunnel %d returned error: %v", i, err)
		}
		_ = conn.Close()
	}

	for i, session := range sessions {
		if got := session.openCount.Load(); got != 2 {
			t.Fatalf("expected session %d open count 2, got %d", i, got)
		}
	}
}

func TestProxySessionPoolSkipsAndReplacesDeadSession(t *testing.T) {
	t.Parallel()

	dead := newMortalProxySession()
	live := newMortalProxySession()
	var created atomic.Int32
	replacement := newMortalProxySession()
	pool, err := newProxySessionPool(2, func() (proxySession, error) {
		switch created.Add(1) {
		case 1:
			return dead, nil
		case 2:
			return live, nil
		default:
			return replacement, nil
		}
	})
	if err != nil {
		t.Fatalf("newProxySessionPool returned error: %v", err)
	}
	defer pool.Close()

	// The keepalive notices the first session died while idle.
	dead.alive.Store(false)

	for i := 0; i < 4; i++ {
		conn, err := pool.OpenTunnel("example.com:443")
		if err != nil {
			t.Fatalf("OpenTunnel %d returned error: %v", i, err)
		}
		_ = conn.Close()
	}

	if got := dead.openCount.Load(); got != 0 {
		t.Fatalf("expected no tunnels on the dead session, got %d", got)
	}
	waitForCondition(t, 2*time.Second, func() bool {
		return created.Load() >= 3
	})
	waitForCondition(t, 2*time.Second, func() bool {
		return dead.closeCount.Load() == 1
	})
}

func TestProxySessionPoolPinsClientToOneSession(t *testing.T) {
	t.Parallel()

	sessions := []*fakeProxySession{{}, {}, {}}
	var created atomic.Int32
	p, err := newProxySessionPool(len(sessions), func() (proxySession, error) {
		idx := int(created.Add(1)) - 1
		if idx >= len(sessions) {
			return nil, errors.New("replacement unavailable")
		}
		return sessions[idx], nil
	})
	if err != nil {
		t.Fatalf("newProxySessionPool returned error: %v", err)
	}
	defer p.Close()

	for i := 0; i < 6; i++ {
		conn, err := p.OpenTunnelForClient("example.com:443", "127.0.0.1")
		if err != nil {
			t.Fatalf("OpenTunnelForClient %d returned error: %v", i, err)
		}
		_ = conn.Close()
	}

	used := 0
	for i, session := range sessions {
		if got := session.openCount.Load(); got > 0 {
			used++
			if got != 6 {
				t.Fatalf("expected pinned session %d to receive all tunnels, got %d", i, got)
			}
		}
	}
	if used != 1 {
		t.Fatalf("expected one session to receive pinned client tunnels, used %d", used)
	}
}

func TestProxySessionPoolKeepsClientOnFailoverSession(t *testing.T) {
	t.Parallel()

	sessions := []*fakeProxySession{{}, {}, {}}
	var created atomic.Int32
	p, err := newProxySessionPool(len(sessions), func() (proxySession, error) {
		idx := int(created.Add(1)) - 1
		if idx >= len(sessions) {
			return nil, errors.New("replacement unavailable")
		}
		return sessions[idx], nil
	})
	if err != nil {
		t.Fatalf("newProxySessionPool returned error: %v", err)
	}
	defer p.Close()

	const clientKey = "127.0.0.1"
	failedSlot := p.nextSlot(clientKey)
	failoverSlot := (failedSlot + 1) % len(sessions)
	sessions[failedSlot].openErr = errors.New("transport closed")

	conn, err := p.OpenTunnelForClient("example.com:443", clientKey)
	if err != nil {
		t.Fatalf("OpenTunnelForClient failover returned error: %v", err)
	}
	_ = conn.Close()

	conn, err = p.OpenTunnelForClient("example.org:443", clientKey)
	if err != nil {
		t.Fatalf("OpenTunnelForClient after failover returned error: %v", err)
	}
	_ = conn.Close()

	if got := sessions[failedSlot].openCount.Load(); got != 1 {
		t.Fatalf("expected failed slot to be tried once, got %d", got)
	}
	if got := sessions[failoverSlot].openCount.Load(); got != 2 {
		t.Fatalf("expected failover slot to remain sticky, got %d opens", got)
	}
}

func TestProxySessionPoolUpdatesExistingAndReplacementTokens(t *testing.T) {
	t.Parallel()

	var factoryMu sync.Mutex
	createToken := "old-token"
	var sessions []*fakeProxySession
	p, err := newProxySessionPool(2, func() (proxySession, error) {
		factoryMu.Lock()
		defer factoryMu.Unlock()
		session := &fakeProxySession{token: createToken}
		sessions = append(sessions, session)
		return session, nil
	}, func(token string) {
		factoryMu.Lock()
		createToken = token
		factoryMu.Unlock()
	})
	if err != nil {
		t.Fatalf("newProxySessionPool returned error: %v", err)
	}
	defer p.Close()

	if err := p.UpdateToken("new-token"); err != nil {
		t.Fatalf("UpdateToken returned error: %v", err)
	}
	factoryMu.Lock()
	initial := append([]*fakeProxySession(nil), sessions...)
	factoryMu.Unlock()
	for i, session := range initial {
		if got := session.currentToken(); got != "new-token" {
			t.Fatalf("expected existing session %d token to update, got %q", i, got)
		}
	}

	failed := p.slot(0)
	p.retireSlot(0, failed)
	waitForCondition(t, time.Second, func() bool {
		factoryMu.Lock()
		defer factoryMu.Unlock()
		return len(sessions) >= 3
	})
	factoryMu.Lock()
	replacement := sessions[len(sessions)-1]
	factoryMu.Unlock()
	if got := replacement.currentToken(); got != "new-token" {
		t.Fatalf("expected replacement session to use renewed token, got %q", got)
	}
}

func TestProxySessionPoolUpdatesReplacementCreatedDuringRenewal(t *testing.T) {
	t.Parallel()

	var factoryMu sync.Mutex
	createToken := "old-token"
	createCalls := 0
	replacementStarted := make(chan struct{})
	releaseReplacement := make(chan struct{})
	var releaseOnce sync.Once
	defer releaseOnce.Do(func() { close(releaseReplacement) })
	var sessions []*fakeProxySession
	p, err := newProxySessionPool(2, func() (proxySession, error) {
		factoryMu.Lock()
		createCalls++
		call := createCalls
		token := createToken
		factoryMu.Unlock()
		if call == 3 {
			close(replacementStarted)
			<-releaseReplacement
		}
		session := &fakeProxySession{token: token}
		factoryMu.Lock()
		sessions = append(sessions, session)
		factoryMu.Unlock()
		return session, nil
	}, func(token string) {
		factoryMu.Lock()
		createToken = token
		factoryMu.Unlock()
	})
	if err != nil {
		t.Fatalf("newProxySessionPool returned error: %v", err)
	}
	defer p.Close()

	p.retireSlot(0, p.slot(0))
	select {
	case <-replacementStarted:
	case <-time.After(time.Second):
		t.Fatal("replacement session creation did not start")
	}
	if err := p.UpdateToken("new-token"); err != nil {
		t.Fatalf("UpdateToken returned error: %v", err)
	}
	releaseOnce.Do(func() { close(releaseReplacement) })
	waitForCondition(t, time.Second, func() bool { return p.slot(0) != nil })

	factoryMu.Lock()
	replacement := sessions[len(sessions)-1]
	factoryMu.Unlock()
	if got := replacement.currentToken(); got != "new-token" {
		t.Fatalf("expected in-flight replacement to receive renewed token, got %q", got)
	}
}

func TestProxySessionPoolSkipsBrokenSession(t *testing.T) {
	t.Parallel()

	broken := &fakeProxySession{openErr: errors.New("transport closed")}
	healthy := &fakeProxySession{}
	replacement := &fakeProxySession{}
	sessions := []*fakeProxySession{broken, healthy, replacement}
	var created atomic.Int32
	pool, err := newProxySessionPool(2, func() (proxySession, error) {
		idx := int(created.Add(1)) - 1
		return sessions[idx], nil
	})
	if err != nil {
		t.Fatalf("newProxySessionPool returned error: %v", err)
	}
	defer pool.Close()

	conn, err := pool.OpenTunnel("example.com:443")
	if err != nil {
		t.Fatalf("OpenTunnel returned error: %v", err)
	}
	_ = conn.Close()

	if got := healthy.openCount.Load(); got != 1 {
		t.Fatalf("expected healthy session open count 1, got %d", got)
	}
	if err := pool.Close(); err != nil {
		t.Fatalf("pool Close returned error: %v", err)
	}
	if got := broken.closeCount.Load(); got != 1 {
		t.Fatalf("expected broken session to be closed once, got %d", got)
	}
}

func TestProxySessionPoolStartsWithPartialSuccess(t *testing.T) {
	t.Parallel()

	session := &fakeProxySession{}
	var attempts atomic.Int32
	pool, err := newProxySessionPool(3, func() (proxySession, error) {
		n := attempts.Add(1)
		if n == 1 {
			return session, nil
		}
		return nil, errors.New("temporary dial failure")
	})
	if err != nil {
		t.Fatalf("newProxySessionPool returned error: %v", err)
	}
	defer pool.Close()

	conn, err := pool.OpenTunnel("example.com:443")
	if err != nil {
		t.Fatalf("OpenTunnel returned error: %v", err)
	}
	_ = conn.Close()
	if got := session.openCount.Load(); got != 1 {
		t.Fatalf("expected available session open count 1, got %d", got)
	}
}

func TestProxySessionPoolReplenishesBrokenSession(t *testing.T) {
	t.Parallel()

	broken := &fakeProxySession{openErr: errors.New("transport closed")}
	healthy := &fakeProxySession{}
	replacement := &fakeProxySession{}
	sessions := []*fakeProxySession{broken, healthy, replacement}
	var created atomic.Int32
	pool, err := newProxySessionPool(2, func() (proxySession, error) {
		idx := int(created.Add(1)) - 1
		if idx >= len(sessions) {
			return nil, errors.New("unexpected extra create")
		}
		return sessions[idx], nil
	})
	if err != nil {
		t.Fatalf("newProxySessionPool returned error: %v", err)
	}
	defer pool.Close()

	conn, err := pool.OpenTunnel("example.com:443")
	if err != nil {
		t.Fatalf("OpenTunnel returned error: %v", err)
	}
	_ = conn.Close()

	waitForCondition(t, time.Second, func() bool {
		return pool.slot(0) != nil
	})

	for i := 0; i < 2; i++ {
		conn, err := pool.OpenTunnel("example.org:443")
		if err != nil {
			t.Fatalf("OpenTunnel after replenish returned error: %v", err)
		}
		_ = conn.Close()
	}
	if got := replacement.openCount.Load(); got == 0 {
		t.Fatal("expected replenished session to receive a tunnel")
	}
}
