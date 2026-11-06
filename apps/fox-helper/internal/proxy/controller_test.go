package proxy

import (
	"errors"
	"fmt"
	"net/http"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

func TestProxyControllerRebuildsKeepAliveDeadSession(t *testing.T) {
	t.Parallel()

	dead := newMortalProxySession()
	fresh := newMortalProxySession()
	var created atomic.Int32
	controller := &Controller{
		current: &managedSession{
			session:   dead,
			expiresAt: time.Now().Add(10 * time.Minute),
			accepting: true,
		},
	}
	controller.refreshSession = func() error {
		created.Add(1)
		controller.swapSession(fresh, "fresh-token", time.Now().Add(20*time.Minute))
		return nil
	}
	dead.alive.Store(false)

	conn, err := controller.OpenTunnel("example.com:443")
	if err != nil {
		t.Fatalf("OpenTunnel returned error: %v", err)
	}
	defer conn.Close()

	if got := dead.openCount.Load(); got != 0 {
		t.Fatalf("expected no tunnel attempt on the dead session, got %d", got)
	}
	if got := fresh.openCount.Load(); got != 1 {
		t.Fatalf("expected the rebuilt session to serve the tunnel, got %d", got)
	}
	if got := created.Load(); got != 1 {
		t.Fatalf("expected exactly one rebuild, got %d", got)
	}
}

func TestProxyControllerSwapDrainsOldSession(t *testing.T) {
	t.Parallel()

	oldSession := &fakeProxySession{}
	newSession := &fakeProxySession{}
	controller := &Controller{
		current: &managedSession{
			session:   oldSession,
			expiresAt: time.Now().Add(10 * time.Minute),
			accepting: true,
		},
	}

	conn1, err := controller.OpenTunnel("example.com:443")
	if err != nil {
		t.Fatalf("OpenTunnel old session failed: %v", err)
	}
	if oldSession.openCount.Load() != 1 {
		t.Fatalf("expected old session open count 1, got %d", oldSession.openCount.Load())
	}

	controller.swapSession(newSession, "new-token", time.Now().Add(20*time.Minute))

	conn2, err := controller.OpenTunnel("example.org:443")
	if err != nil {
		t.Fatalf("OpenTunnel new session failed: %v", err)
	}
	if newSession.openCount.Load() != 1 {
		t.Fatalf("expected new session open count 1, got %d", newSession.openCount.Load())
	}
	if oldSession.closeCount.Load() != 0 {
		t.Fatalf("old session closed too early: %d", oldSession.closeCount.Load())
	}

	_ = conn2.Close()
	if newSession.closeCount.Load() != 0 {
		t.Fatalf("new current session should remain open, got close count %d", newSession.closeCount.Load())
	}

	_ = conn1.Close()
	if oldSession.closeCount.Load() != 1 {
		t.Fatalf("expected old session to close after draining, got %d", oldSession.closeCount.Load())
	}
}

func TestProxyControllerUpdatesTokenWithoutReplacingSession(t *testing.T) {
	t.Parallel()

	session := &fakeProxySession{token: "old-token"}
	oldExpiry := time.Now().Add(10 * time.Minute)
	newExpiry := time.Now().Add(20 * time.Minute)
	controller := &Controller{
		current: &managedSession{
			session:   session,
			expiresAt: oldExpiry,
			accepting: true,
		},
	}

	if err := controller.updateCurrentSessionToken("new-token", newExpiry); err != nil {
		t.Fatalf("updateCurrentSessionToken returned error: %v", err)
	}
	if controller.current.session != session {
		t.Fatal("expected token renewal to retain the existing upstream session")
	}
	if got := session.currentToken(); got != "new-token" {
		t.Fatalf("expected renewed token, got %q", got)
	}
	if !controller.current.expiresAt.Equal(newExpiry) {
		t.Fatalf("expected expiry %s, got %s", newExpiry, controller.current.expiresAt)
	}
	if session.closeCount.Load() != 0 {
		t.Fatalf("expected retained session to stay open, got %d closes", session.closeCount.Load())
	}
}

func TestProxyControllerRejectsSessionSwapAfterClose(t *testing.T) {
	t.Parallel()

	controller := &Controller{closed: true}
	newSession := &fakeProxySession{}
	if controller.swapSession(newSession, "new-token", time.Now().Add(time.Minute)) {
		t.Fatal("expected closed controller to reject session swap")
	}
	if got := newSession.closeCount.Load(); got != 1 {
		t.Fatalf("expected rejected session to be closed once, got %d", got)
	}
}

func TestProxyControllerDisableExpiredSessionRejectsNewTunnels(t *testing.T) {
	t.Parallel()

	session := &fakeProxySession{}
	controller := &Controller{
		current: &managedSession{
			session:   session,
			expiresAt: time.Now().Add(10 * time.Minute),
			accepting: true,
		},
	}
	controller.refreshSession = func() error {
		return ErrNoUsableSession
	}

	conn, err := controller.OpenTunnel("example.com:443")
	if err != nil {
		t.Fatalf("OpenTunnel failed: %v", err)
	}

	controller.disableExpiredSession(time.Now().Add(11 * time.Minute))

	_, err = controller.OpenTunnel("example.org:443")
	if !errors.Is(err, ErrNoUsableSession) {
		t.Fatalf("expected errNoUsableProxySession, got %v", err)
	}
	if session.closeCount.Load() != 0 {
		t.Fatalf("session closed while active tunnel exists: %d", session.closeCount.Load())
	}

	_ = conn.Close()
	if session.closeCount.Load() != 1 {
		t.Fatalf("expected session close after active tunnel drained, got %d", session.closeCount.Load())
	}
}

func TestProxyControllerRebuildsSessionAfterOpenTunnelFailure(t *testing.T) {
	t.Parallel()

	failedSession := &fakeProxySession{openErr: errors.New("upstream session is gone")}
	newSession := &fakeProxySession{}
	controller := &Controller{
		current: &managedSession{
			session:   failedSession,
			expiresAt: time.Now().Add(10 * time.Minute),
			accepting: true,
		},
	}
	controller.refreshSession = func() error {
		controller.swapSession(newSession, "new-token", time.Now().Add(20*time.Minute))
		return nil
	}

	conn, err := controller.OpenTunnel("example.com:443")
	if err != nil {
		t.Fatalf("OpenTunnel after rebuild failed: %v", err)
	}
	_ = conn.Close()

	if failedSession.openCount.Load() != 1 {
		t.Fatalf("expected failed session open count 1, got %d", failedSession.openCount.Load())
	}
	if failedSession.closeCount.Load() != 1 {
		t.Fatalf("expected failed session to close after rebuild, got %d", failedSession.closeCount.Load())
	}
	if newSession.openCount.Load() != 1 {
		t.Fatalf("expected new session open count 1, got %d", newSession.openCount.Load())
	}
}

func TestProxyControllerDoesNotRebuildForConnectHTTPFailure(t *testing.T) {
	t.Parallel()

	session := &fakeProxySession{
		openErr: &proxyConnectHTTPError{
			statusCode: http.StatusBadGateway,
			status:     "502 Bad Gateway",
			body:       "target unreachable",
		},
	}
	controller := &Controller{
		current: &managedSession{
			session:   session,
			expiresAt: time.Now().Add(10 * time.Minute),
			accepting: true,
		},
	}
	var rebuilds atomic.Int32
	controller.refreshSession = func() error {
		rebuilds.Add(1)
		return nil
	}

	_, err := controller.OpenTunnel("example.com:443")
	if err == nil {
		t.Fatal("expected OpenTunnel to fail")
	}
	var connectErr *proxyConnectHTTPError
	if !errors.As(err, &connectErr) {
		t.Fatalf("expected proxyConnectHTTPError, got %v", err)
	}
	if rebuilds.Load() != 0 {
		t.Fatalf("expected no rebuilds, got %d", rebuilds.Load())
	}
	if session.closeCount.Load() != 0 {
		t.Fatalf("expected current session to remain open, got close count %d", session.closeCount.Load())
	}
	if !controller.current.accepting {
		t.Fatal("expected current session to remain accepting")
	}
}

func TestProxyControllerStopsAfterThreeOpenTunnelRebuilds(t *testing.T) {
	t.Parallel()

	controller := &Controller{
		current: &managedSession{
			session:   &fakeProxySession{openErr: errors.New("initial session failed")},
			expiresAt: time.Now().Add(10 * time.Minute),
			accepting: true,
		},
	}
	var rebuilds atomic.Int32
	controller.refreshSession = func() error {
		n := rebuilds.Add(1)
		controller.swapSession(
			&fakeProxySession{openErr: fmt.Errorf("rebuilt session %d failed", n)},
			fmt.Sprintf("rebuilt-token-%d", n),
			time.Now().Add(20*time.Minute),
		)
		return nil
	}

	_, err := controller.OpenTunnel("example.com:443")
	if err == nil {
		t.Fatal("expected OpenTunnel to fail")
	}
	if rebuilds.Load() != maxOpenTunnelRebuildRetries {
		t.Fatalf("expected %d rebuilds, got %d", maxOpenTunnelRebuildRetries, rebuilds.Load())
	}
}

func TestProxyControllerKeepsRebuildErrorWhenSessionUnavailable(t *testing.T) {
	t.Parallel()

	controller := &Controller{
		current: &managedSession{
			session:   &fakeProxySession{openErr: errors.New("initial session failed")},
			expiresAt: time.Now().Add(10 * time.Minute),
			accepting: true,
		},
	}
	var rebuilds atomic.Int32
	controller.refreshSession = func() error {
		rebuilds.Add(1)
		return errors.New("refresh token rejected")
	}

	_, err := controller.OpenTunnel("example.com:443")
	if err == nil {
		t.Fatal("expected OpenTunnel to fail")
	}
	if !strings.Contains(err.Error(), "refresh token rejected") {
		t.Fatalf("expected rebuild error to be preserved, got %v", err)
	}
	if rebuilds.Load() != maxOpenTunnelRebuildRetries {
		t.Fatalf("expected %d rebuilds, got %d", maxOpenTunnelRebuildRetries, rebuilds.Load())
	}
}

func TestProxyControllerSkipsRebuildWhenSessionAlreadyReplaced(t *testing.T) {
	t.Parallel()

	oldSession := &fakeProxySession{}
	newSession := &fakeProxySession{}
	controller := &Controller{
		current: &managedSession{
			session:   oldSession,
			expiresAt: time.Now().Add(10 * time.Minute),
			accepting: true,
		},
	}
	failed := controller.current
	controller.swapSession(newSession, "new-token", time.Now().Add(20*time.Minute))

	var rebuilds atomic.Int32
	controller.refreshSession = func() error {
		rebuilds.Add(1)
		return nil
	}

	if err := controller.rebuildSession(failed, errProxySessionUnhealthy); err != nil {
		t.Fatalf("rebuildSession returned error: %v", err)
	}
	if rebuilds.Load() != 0 {
		t.Fatalf("expected rebuild to be skipped, got %d rebuilds", rebuilds.Load())
	}
}
