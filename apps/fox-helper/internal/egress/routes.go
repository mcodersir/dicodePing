//go:build windows || darwin || (linux && !android)

package egress

import (
	"sync"
	"time"
)

// routesCache keeps the default-route interfaces a moment, for the
// connections a page opens at once.
var routesCache struct {
	mu     sync.Mutex
	at     time.Time
	tun    tunState
	v4, v6 uint32
	ok4    bool
	ok6    bool
}

const routesFresh = time.Second

func forget() {
	routesCache.mu.Lock()
	routesCache.at = time.Time{}
	routesCache.mu.Unlock()
}

// physical is the interface of the default route (defaultInterface: up,
// and not the TUN adapter st).
func physical(v6 bool, st *tunState) (uint32, bool) {
	routesCache.mu.Lock()
	defer routesCache.mu.Unlock()
	if routesCache.tun != *st || time.Since(routesCache.at) > routesFresh {
		routesCache.v4, routesCache.ok4 = defaultInterface(false, st)
		routesCache.v6, routesCache.ok6 = defaultInterface(true, st)
		routesCache.tun, routesCache.at = *st, time.Now()
	}
	if v6 {
		return routesCache.v6, routesCache.ok6
	}
	return routesCache.v4, routesCache.ok4
}
