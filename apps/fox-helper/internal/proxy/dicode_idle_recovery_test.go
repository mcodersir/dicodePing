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
