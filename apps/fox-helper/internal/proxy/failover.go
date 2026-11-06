package proxy

import (
	"context"
	"errors"
	"fmt"
	"net"
	"net/http"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"dicodeping/fox/internal/logx"
)

const (
	// serverFailoverStrikes is how many failures in a row of one server
	// move the upstream to another server of the location. A rebuild
	// counts once, and rebuilds are spaced (redials 0, 10 s, 30 s; new
	// passes 10 s apart and more), so a dead server is left within about
	// 10 to 40 seconds; one or two failures in a row are what a short
	// network blip (a Wi-Fi roam, a mobile handover) does, and must not
	// move the server. It matches the failure tracker's three distinct
	// failing targets.
	serverFailoverStrikes = 3

	// serverAvoidTime is how long a server that reached
	// serverFailoverStrikes is skipped. It outlasts several rounds of the
	// longest rebuild spacing (2 minutes), so the location's other servers
	// are tried before it, and is short enough that a server back from a
	// restart or a short outage returns to the choice within a quarter of
	// an hour.
	serverAvoidTime = 15 * time.Minute

	// serverDropLimit failures of one server within serverDropWindow move
	// the upstream too, also when tunnels opened between them (which clears
	// the strikes in a row): a network that cuts the connection to the
	// server every minute or so, as some Iranian networks do, lets every new
	// session work for a while and then drops it. A short blip is one or
	// two drops; four in five minutes is a server this network will not
	// keep.
	serverDropLimit  = 4
	serverDropWindow = 5 * time.Minute
)

// ServerFailover moves the upstream to another server of the chosen
// location when one server keeps failing: after serverFailoverStrikes
// failures in a row to establish or keep a session on it, or
// serverDropLimit within serverDropWindow (serverFault decides which
// failures are the server's), the server is avoided for serverAvoidTime
// and another server of the same city, else of the location's next city,
// is used and saved as the persisted choice. A location may have stand-ins
// (the recommended location, which has one server): when none of its own
// servers is left, the first stand-in is used for the time being, and not
// saved. When every other server is avoided, the upstream stays where it
// is and the usual retries go on.
//
// One per daemon: it outlives controllers and engines, so the wakes and
// the controllers of one location share the strikes and the avoided
// servers. A nil ServerFailover does nothing (a server set by hand).
type ServerFailover struct {
	// selectionFile is where a new choice is saved (selection.json); empty
	// saves nothing.
	selectionFile string
	// now is the clock; tests replace it.
	now func() time.Time
	// pending is set while a server has strikes, so Worked, called for
	// every tunnel, takes no lock otherwise.
	pending atomic.Bool

	mu sync.Mutex
	// failing is the canonical address of the server with strikes.
	failing string
	strikes int
	// drops maps canonical addresses to the times of their recent failures
	// (within serverDropWindow).
	drops map[string][]time.Time
	// avoided maps canonical addresses to the end of their avoidance.
	avoided map[string]time.Time
}

// NewServerFailover returns a failover that saves new choices in
// selectionFile.
func NewServerFailover(selectionFile string) *ServerFailover {
	return &ServerFailover{selectionFile: selectionFile, now: time.Now}
}

// Avoided reports whether the server at addr failed recently and is
// skipped by selection.
func (f *ServerFailover) Avoided(addr string) bool {
	if f == nil {
		return false
	}
	key, err := canonicalProxyAddr(addr)
	if err != nil {
		return false
	}
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.avoidedLocked(key, f.now())
}

func (f *ServerFailover) avoidedLocked(key string, now time.Time) bool {
	until, ok := f.avoided[key]
	if ok && !now.Before(until) {
		delete(f.avoided, key)
		return false
	}
	return ok
}

// Worked forgets the strikes of the server at addr: a tunnel opened
// through it.
func (f *ServerFailover) Worked(addr string) {
	if f == nil || !f.pending.Load() {
		return
	}
	key, err := canonicalProxyAddr(addr)
	if err != nil {
		return
	}
	f.mu.Lock()
	if f.failing == key {
		f.failing, f.strikes = "", 0
		f.pending.Store(false)
	}
	f.mu.Unlock()
}

// Failed counts err against server, one of location's servers or of its
// stand-ins (fallback), when the server is to blame (serverFault). At its
// serverFailoverStrikes-th failure in a row, or its serverDropLimit-th
// within serverDropWindow, the server is avoided for serverAvoidTime and
// Failed returns the server to use instead (nextServer, the location's
// servers before the stand-ins), saved as the persisted choice when it is
// the location's. ok is false otherwise, also when every other server is
// avoided: the caller then stays on server.
func (f *ServerFailover) Failed(location, fallback []Candidate, server Candidate, err error) (next Candidate, ok bool) {
	if f == nil || !serverFault(err) {
		return Candidate{}, false
	}
	key, keyErr := canonicalProxyAddr(server.Addr)
	if keyErr != nil {
		return Candidate{}, false
	}
	now := f.now()
	f.mu.Lock()
	if f.failing != key {
		f.failing, f.strikes = key, 0
	}
	f.strikes++
	f.pending.Store(true)
	drops := f.dropLocked(key, now)
	if f.strikes < serverFailoverStrikes && drops < serverDropLimit {
		strikes := f.strikes
		f.mu.Unlock()
		logx.Debug("upstream server failed proxy=%s failures_in_a_row=%d failures_in_%s=%d err=%s",
			server.Addr, strikes, serverDropWindow, drops, logx.Err(err))
		return Candidate{}, false
	}
	why := fmt.Sprintf("failed %d times in a row", f.strikes)
	if f.strikes < serverFailoverStrikes {
		why = fmt.Sprintf("lost its connection %d times in %s", drops, serverDropWindow)
	}
	f.failing, f.strikes = "", 0
	f.pending.Store(false)
	delete(f.drops, key)
	if f.avoided == nil {
		f.avoided = make(map[string]time.Time)
	}
	f.avoided[key] = now.Add(serverAvoidTime)
	choices := append(append([]Candidate(nil), location...), fallback...)
	next, ok = nextServer(choices, server, func(addr string) bool {
		k, err := canonicalProxyAddr(addr)
		return err == nil && f.avoidedLocked(k, now)
	})
	f.mu.Unlock()

	if !ok {
		logx.Warn("upstream server %s, and every other server failed recently; staying on it proxy=%s err=%s",
			why, server.Addr, logx.Err(err))
		return Candidate{}, false
	}
	if !inLocation(location, next.Addr) {
		logx.Info("upstream server %s, and the location has no other; using another location's server for now from=%s to=%s country=%s avoid_for=%s err=%s",
			why, server.Addr, next.Addr, next.CountryCodeOrUnknown(), serverAvoidTime, logx.Err(err))
		return next, true
	}
	logx.Info("upstream server %s; switching to another server of the location from=%s to=%s city=%q avoid_for=%s err=%s",
		why, server.Addr, next.Addr, next.CityNameOrUnknown(), serverAvoidTime, logx.Err(err))
	if f.selectionFile != "" {
		if err := SaveSelection(f.selectionFile, next); err != nil {
			logx.Warn("saving proxy selection failed path=%s err=%s", f.selectionFile, logx.Err(err))
		}
	}
	return next, true
}

// dropLocked records a failure of the server key at now and returns how
// many it had within serverDropWindow, this one included.
func (f *ServerFailover) dropLocked(key string, now time.Time) int {
	if f.drops == nil {
		f.drops = make(map[string][]time.Time)
	}
	recent := f.drops[key][:0]
	for _, at := range f.drops[key] {
		if now.Sub(at) < serverDropWindow {
			recent = append(recent, at)
		}
	}
	recent = append(recent, now)
	f.drops[key] = recent
	return len(recent)
}

// Instead returns the server to connect to in place of server, one of
// location's, while server is avoided: another of the location's servers,
// else a stand-in (fallback). ok is false when server is not avoided or
// nothing else is left.
func (f *ServerFailover) Instead(location, fallback []Candidate, server Candidate) (Candidate, bool) {
	if f == nil || !f.Avoided(server.Addr) {
		return Candidate{}, false
	}
	choices := append(append([]Candidate(nil), location...), fallback...)
	return nextServer(choices, server, f.Avoided)
}

// StandInAfterTimeout picks a server for an immediate retry of a first
// connection to the recommended location. A network or account failure
// shared by all servers still uses the normal wake retry policy.
func (f *ServerFailover) StandInAfterTimeout(fallback []Candidate, server Candidate, err error) (Candidate, bool) {
	var timeout net.Error
	if f == nil || !server.IsRecommended() || FailureCode(err) != FailureUnreachable ||
		!errors.As(err, &timeout) || !timeout.Timeout() {
		return Candidate{}, false
	}
	return nextServer(fallback, server, f.Avoided)
}

// StandInConnected keeps the timed-out server out of the choice after its
// stand-in has established a session. A failed stand-in leaves the usual
// failure thresholds in charge.
func (f *ServerFailover) StandInConnected(server Candidate) {
	key, err := canonicalProxyAddr(server.Addr)
	if err != nil {
		return
	}
	f.mu.Lock()
	defer f.mu.Unlock()
	if f.avoided == nil {
		f.avoided = make(map[string]time.Time)
	}
	f.avoided[key] = f.now().Add(serverAvoidTime)
}

// inLocation reports whether addr is one of location's servers.
func inLocation(location []Candidate, addr string) bool {
	key, err := canonicalProxyAddr(addr)
	if err != nil {
		return false
	}
	for _, c := range location {
		if k, err := canonicalProxyAddr(c.Addr); err == nil && k == key {
			return true
		}
	}
	return false
}

// nextServer picks the server to use instead of current: another server
// of current's city, else one of the location's first other city that has
// one, at random within the city (as pickInFirstCity does), skipping
// avoided servers.
func nextServer(location []Candidate, current Candidate, avoided func(addr string) bool) (Candidate, bool) {
	currentKey, _ := canonicalProxyAddr(current.Addr)
	usable := func(c Candidate) bool {
		key, err := canonicalProxyAddr(c.Addr)
		return err == nil && key != currentKey && !avoided(c.Addr)
	}
	if next, ok := pickInFirstCity(location, func(c Candidate) bool { return sameCity(c, current) && usable(c) }); ok {
		return next, true
	}
	return pickInFirstCity(location, usable)
}

// sameCity reports whether a and b are servers of one city.
func sameCity(a, b Candidate) bool {
	return strings.EqualFold(a.CountryCode, b.CountryCode) && a.CityCode == b.CityCode && a.CityName == b.CityName
}

// serverFault reports whether err, a failure to establish or keep a
// session on a Mozilla proxy server, can be blamed on that server. It
// cannot when this device has no network, when the account or its pass is
// the problem (Guardian's answers; a CONNECT 401, 403, 407, or 429), when
// the attempt was cancelled or did not happen (a rebuild cooling down, no
// session to use), or for a port Mozilla's proxy refuses (such a 502 never
// gets here: it neither rebuilds nor marks a session unhealthy).
func serverFault(err error) bool {
	if err == nil ||
		errors.Is(err, context.Canceled) ||
		errors.Is(err, errRebuildCoolingDown) ||
		errors.Is(err, ErrNoUsableSession) ||
		errors.Is(err, errSessionSaturated) {
		return false
	}
	switch FailureCode(err) {
	case FailureNoNetwork, FailureSignIn, FailureQuota, FailureNotEntitled, FailureRegion,
		FailureNoAccount, FailureServer, FailureLocationRefused:
		return false
	}
	var connectErr *proxyConnectHTTPError
	if errors.As(err, &connectErr) {
		switch connectErr.statusCode {
		case http.StatusUnauthorized, http.StatusForbidden, http.StatusProxyAuthRequired, http.StatusTooManyRequests:
			return false
		}
	}
	return true
}
