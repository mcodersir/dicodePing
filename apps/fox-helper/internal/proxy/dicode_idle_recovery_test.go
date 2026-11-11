package proxy

import (
    "sync/atomic"
    "testing"
    "time"
)

// No OpenTunnel call may be needed to replace a session whose own keepalive
// already marked it dead. Otherwise applications' own retry delays extend an
// outage after the network has recovered.
func TestPoolRestoresDeadIdleSlotWithoutAClientRequest(t *testing.T) {
    t.Parallel()
    first := newMortalProxySession()
    replacement := newMortalProxySession()
    var created atomic.Int32
    pool, err := newProxySessionPool(1, func() (proxySession, error) {
        if created.Add(1) == 1 { return first, nil }
        return replacement, nil
    })
    if err != nil { t.Fatal(err) }
    defer pool.Close()
    first.alive.Store(false)
    waitForCondition(t, 2*time.Second, func() bool { return created.Load() == 2 })
    if replacement.openCount.Load() != 0 { t.Fatal("Recovery sent application traffic") }
    waitForCondition(t, time.Second, func() bool { return first.closeCount.Load() == 1 })
}

func TestPoolRetryIsQuickInitiallyAndBoundedUnderAProlongedOutage(t *testing.T) {
    for _, tc := range []struct { attempt int; want time.Duration }{
        {1, 500*time.Millisecond}, {2, time.Second}, {3, 2*time.Second}, {20, 10*time.Second},
    } {
        if got := poolRetryDelay(tc.attempt, 0); got != tc.want { t.Fatalf("attempt=%d delay=%s want=%s", tc.attempt, got, tc.want) }
    }
    if poolRetryDelay(1, 0) == poolRetryDelay(1, 1) { t.Fatal("Pool slots retry in lockstep") }
}

func TestPoolMonitorLeavesHealthySessionsAloneAndStopsOnClose(t *testing.T) {
    t.Parallel()
    session := newMortalProxySession()
    var created atomic.Int32
    pool, err := newProxySessionPool(1, func() (proxySession, error) { created.Add(1); return session, nil })
    if err != nil { t.Fatal(err) }
    defer pool.Close()
    time.Sleep(2 * upstreamSessionHealthInterval)
    if created.Load() != 1 || session.closeCount.Load() != 0 { t.Fatal("A healthy session was churned") }
    _ = pool.Close()
    session.alive.Store(false)
    time.Sleep(2 * upstreamSessionHealthInterval)
    if created.Load() != 1 { t.Fatal("Recovery continued after intentional close") }
}
