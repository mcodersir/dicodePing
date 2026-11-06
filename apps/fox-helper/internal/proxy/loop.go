package proxy

import (
	"sync"
	"time"
)

// A loop is this program's own connections coming back to its proxy as a
// client's: a program sends this program's traffic into the proxy
// (PassWall2's Localhost Proxy, another VPN program's TUN), and nothing
// connects, since the proxy needs those very connections to reach Mozilla.
// One client's connection to an address this program also used (a
// browser's DNS over HTTPS at 1.1.1.1) is chance; two different such
// addresses within loopWindow are a loop (loopWatch).

const (
	loopWindow    = 10 * time.Second
	loopWarnEvery = time.Minute
)

// loopWatch keeps the own addresses that came back lately.
type loopWatch struct {
	mu     sync.Mutex
	seen   map[string]time.Time
	warned time.Time
}

var loops loopWatch

// note records that target, one of this program's own addresses, came back
// as a client's, and reports whether that makes a loop, and whether to
// warn of it now (once a minute).
func (w *loopWatch) note(target string, now time.Time) (loop, warn bool) {
	w.mu.Lock()
	defer w.mu.Unlock()
	if w.seen == nil {
		w.seen = map[string]time.Time{}
	}
	for t, at := range w.seen {
		if now.Sub(at) > loopWindow {
			delete(w.seen, t)
		}
	}
	w.seen[target] = now
	if len(w.seen) < 2 {
		return false, false
	}
	if now.Sub(w.warned) >= loopWarnEvery {
		w.warned = now
		return true, true
	}
	return true, false
}
