package proxy

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"path/filepath"
	"sync"
	"testing"
	"time"

	"dicodeping/fox/internal/accounts"
	"dicodeping/fox/internal/fxa"
	"dicodeping/fox/internal/guardian"
	"dicodeping/fox/internal/serverlist"
)

// failoverCountries has Germany with two servers in Berlin and one in
// Frankfurt, and France with one in Paris.
func failoverCountries() []serverlist.Country {
	server := func(host string) serverlist.Server { return serverlist.Server{Hostname: host, Port: 2499} }
	return []serverlist.Country{
		{Name: "Germany", Code: "DE", Cities: []serverlist.City{
			{Name: "Berlin", Code: "ber", Servers: []serverlist.Server{server("a.example"), server("b.example")}},
			{Name: "Frankfurt", Code: "fra", Servers: []serverlist.Server{server("c.example")}},
		}},
		{Name: "France", Code: "FR", Cities: []serverlist.City{
			{Name: "Paris", Code: "par", Servers: []serverlist.Server{server("fr.example")}},
		}},
	}
}

const (
	serverA = "a.example:2499"
	serverB = "b.example:2499"
	serverC = "c.example:2499"
)

// errServerReset is a failure of the server: the connection was cut.
var errServerReset = errors.New("read tcp: connection reset by peer")

// failoverFixture is a controller on server A of the German location whose
// session has died, with a failover that saves to a temporary
// selection.json. Its sessions dial the controller's current server and
// fail with down[server], or succeed.
type failoverFixture struct {
	c         *Controller
	failover  *ServerFailover
	selection string
	location  []Candidate

	mu       sync.Mutex
	down     map[string]error
	dialed   []string
	switched []string
}

func newFailoverFixture(t *testing.T, down map[string]error) *failoverFixture {
	t.Helper()
	location := LocationCandidates(failoverCountries(), "DE")
	if len(location) != 3 || location[0].Addr != serverA {
		t.Fatalf("location %v", location)
	}
	f := &failoverFixture{
		selection: filepath.Join(t.TempDir(), "selection.json"),
		location:  location,
		down:      down,
	}
	if err := SaveSelection(f.selection, location[0]); err != nil {
		t.Fatal(err)
	}
	f.failover = NewServerFailover(f.selection)
	target, err := NormalizeURL(serverA)
	if err != nil {
		t.Fatal(err)
	}
	dead := newMortalProxySession()
	dead.alive.Store(false)
	c := &Controller{
		server:   location[0],
		proxyURL: target,
		location: location,
		failover: f.failover,
		current: &managedSession{
			session:   dead,
			rawToken:  "pass-1",
			expiresAt: time.Now().Add(time.Hour),
			accepting: true,
			server:    serverA,
		},
	}
	c.sessionFactory = func(token string) (proxySession, error) {
		addr := c.currentServer().Addr
		f.mu.Lock()
		defer f.mu.Unlock()
		f.dialed = append(f.dialed, addr)
		if err := f.down[addr]; err != nil {
			return nil, err
		}
		return &fakeProxySession{}, nil
	}
	c.OnServerSwitched = func(next Candidate) {
		f.mu.Lock()
		f.switched = append(f.switched, next.Addr)
		f.mu.Unlock()
	}
	f.c = c
	return f
}

func (f *failoverFixture) dials() []string {
	f.mu.Lock()
	defer f.mu.Unlock()
	return append([]string(nil), f.dialed...)
}

func (f *failoverFixture) persisted(t *testing.T) string {
	t.Helper()
	got, err := loadProxySelection(f.selection)
	if err != nil {
		t.Fatal(err)
	}
	return got.Addr
}

// withGuardian gives the fixture's controller an account whose new passes
// a local Guardian stand-in grants, so rebuilds that need a pass dial.
func (f *failoverFixture) withGuardian(t *testing.T) {
	t.Helper()
	setCoreControlPlane(t, func(r *http.Request) (*http.Response, error) {
		return coreResponse(r, http.StatusOK, `{"token":"`+coreFixtureJWT(time.Hour)+`"}`, quotaHeader(1)), nil
	})
	f.c.guardian = "https://guardian.invalid"
	f.c.auth = &runtimeAuth{Token: &fxa.TokenResponse{AccessToken: "access-a", RefreshToken: "refresh-a", ExpiresIn: 3600}, ObtainedAt: time.Now()}
}

// request opens a tunnel as the next client request after the spacing of
// new passes.
func (f *failoverFixture) request() (net.Conn, error) {
	f.c.renewMu.Lock()
	f.c.passBackoff.lastAt = time.Now().Add(-time.Hour)
	f.c.renewMu.Unlock()
	return f.c.OpenTunnel("example.com:443")
}

// noRedialWait lets a test rebuild without the spacing between redials.
func noRedialWait(t *testing.T) {
	old := redialSteps
	redialSteps = []time.Duration{0}
	t.Cleanup(func() { redialSteps = old })
}

// A server that fails three times in a row gives way to another server of
// its city, at once; the failed one is avoided and the persisted choice
// follows.
func TestServerFailingThreeTimesSwitchesToAnotherServerOfItsCity(t *testing.T) {
	noRedialWait(t)
	f := newFailoverFixture(t, map[string]error{serverA: errServerReset})

	conn, err := f.c.OpenTunnel("example.com:443")
	if err != nil {
		t.Fatalf("OpenTunnel: %v", err)
	}
	_ = conn.Close()
	if got, want := fmt.Sprint(f.dials()), fmt.Sprint([]string{serverA, serverA, serverA, serverB}); got != want {
		t.Fatalf("dialed %s, want %s", got, want)
	}
	if got := f.c.currentServer().Addr; got != serverB {
		t.Fatalf("current server %s, want %s", got, serverB)
	}
	if got := f.persisted(t); got != serverB {
		t.Fatalf("persisted %s, want %s", got, serverB)
	}
	if fmt.Sprint(f.switched) != fmt.Sprint([]string{serverB}) {
		t.Fatalf("OnServerSwitched got %v", f.switched)
	}
	if !f.failover.Avoided(serverA) || f.failover.Avoided(serverB) {
		t.Fatal("A must be avoided, B not")
	}
	// A restart selects the persisted server, not the failed one.
	got, fromState, err := ResolveWithStateAndCountry("", "DE", failoverCountries(), f.selection, nil)
	if err != nil || !fromState || got.Addr != serverB {
		t.Fatalf("after a restart: %v fromState=%v err=%v", got.Addr, fromState, err)
	}
}

// Client requests that come one by one rebuild with new passes once a
// redial failed (no session left): the dials of those passes count too.
func TestServerFailoverCountsTheDialsOfNewPasses(t *testing.T) {
	f := newFailoverFixture(t, map[string]error{serverA: errServerReset})
	f.withGuardian(t)

	// The dead session (1), then a new pass whose session fails (2).
	for range 2 {
		if _, err := f.c.OpenTunnel("example.com:443"); err == nil {
			t.Fatal("server A is down")
		}
	}
	if got := f.c.currentServer().Addr; got != serverA {
		t.Fatalf("switched after two failures, to %s", got)
	}
	// The next new pass (after its 10 s spacing): the third failure moves
	// the session to B.
	conn, err := f.request()
	if err != nil {
		t.Fatalf("OpenTunnel after the switch: %v (dialed %v)", err, f.dials())
	}
	_ = conn.Close()
	if got := f.c.currentServer().Addr; got != serverB || f.persisted(t) != serverB {
		t.Fatalf("current %s, persisted %s; want %s", got, f.persisted(t), serverB)
	}
}

// breakSession makes f's current session fail on the server and rebuilds
// it, as a tunnel that found it dead does.
func (f *failoverFixture) breakSession(t *testing.T) {
	t.Helper()
	f.c.mu.Lock()
	failed := f.c.current
	f.c.mu.Unlock()
	f.c.markSessionUnusable(failed)
	if err := f.c.rebuildSession(failed, errProxySessionUnhealthy); err != nil {
		t.Fatalf("rebuild: %v", err)
	}
}

// tunnel opens a tunnel through f's controller and closes it.
func (f *failoverFixture) tunnel(t *testing.T) {
	t.Helper()
	conn, err := f.c.OpenTunnel("example.com:443")
	if err != nil {
		t.Fatal(err)
	}
	_ = conn.Close()
}

// Sessions that open but break on the server count as well; a tunnel that
// opens in between starts the count in a row again.
func TestBrokenSessionsMoveTheServer(t *testing.T) {
	noRedialWait(t)
	f := newFailoverFixture(t, nil)
	clock := time.Now()
	f.failover.now = func() time.Time { return clock }
	breakSession := func() { t.Helper(); f.breakSession(t) }
	breakSession()
	breakSession()
	f.tunnel(t)
	// Later than the drop window, so only the count in a row could move it.
	clock = clock.Add(serverDropWindow)
	breakSession()
	breakSession()
	if got := f.c.currentServer().Addr; got != serverA {
		t.Fatalf("a tunnel that opened must reset the count; on %s", got)
	}
	breakSession()
	if got := f.c.currentServer().Addr; got != serverB || f.persisted(t) != serverB {
		t.Fatalf("current %s, persisted %s; want %s", got, f.persisted(t), serverB)
	}
	f.c.mu.Lock()
	on := f.c.current.server
	f.c.mu.Unlock()
	if on != serverB {
		t.Fatalf("the current session is on %s, want %s", on, serverB)
	}
}

// A server whose sessions keep breaking moves even when tunnels open
// between the breaks, as on a network that cuts the connection to it
// every minute or so; breaks spread wider than the window do not.
func TestDroppingSessionsMoveTheServer(t *testing.T) {
	noRedialWait(t)
	f := newFailoverFixture(t, nil)
	clock := time.Now()
	f.failover.now = func() time.Time { return clock }
	for range serverDropLimit - 1 {
		f.breakSession(t)
		f.tunnel(t)
		clock = clock.Add(time.Minute)
	}
	if got := f.c.currentServer().Addr; got != serverA {
		t.Fatalf("after %d drops: on %s, want A", serverDropLimit-1, got)
	}
	f.breakSession(t)
	if got := f.c.currentServer().Addr; got != serverB {
		t.Fatalf("after %d drops in %s: on %s, want B", serverDropLimit, serverDropWindow, got)
	}

	g := newFailoverFixture(t, nil)
	g.failover.now = func() time.Time { return clock }
	for range 2 * serverDropLimit {
		g.breakSession(t)
		g.tunnel(t)
		clock = clock.Add(serverDropWindow / (serverDropLimit - 1))
	}
	if got := g.c.currentServer().Addr; got != serverA {
		t.Fatalf("drops spread wider than the window moved the server to %s", got)
	}
}

// The recommended location has one server: when it keeps failing, a
// stand-in of another location takes over, is not saved as the choice,
// and gives way to the recommended server once its avoidance is over.
func TestRecommendedLocationUsesAStandIn(t *testing.T) {
	noRedialWait(t)
	f := newFailoverFixture(t, nil)
	clock := time.Now()
	f.failover.now = func() time.Time { return clock }
	location := f.c.location
	rec, standIn := location[0], location[2]
	f.c.location = []Candidate{rec}
	f.c.fallback = func() []Candidate { return []Candidate{standIn} }
	if err := SaveSelection(f.failover.selectionFile, rec); err != nil {
		t.Fatal(err)
	}
	for range serverFailoverStrikes {
		f.breakSession(t)
	}
	if got := f.c.currentServer().Addr; got != standIn.Addr {
		t.Fatalf("on %s, want the stand-in %s", got, standIn.Addr)
	}
	if got := f.persisted(t); got != rec.Addr {
		t.Fatalf("persisted %s; the stand-in must not be saved", got)
	}
	if next, ok := f.failover.Instead(f.c.location, f.c.fallback(), rec); !ok || next.Addr != standIn.Addr {
		t.Fatalf("a new connection while the server is avoided: %s %v", next.Addr, ok)
	}

	f.breakSession(t)
	if got := f.c.currentServer().Addr; got != standIn.Addr {
		t.Fatalf("returned to %s while it is avoided", got)
	}
	clock = clock.Add(serverAvoidTime)
	f.breakSession(t)
	if got := f.c.currentServer().Addr; got != rec.Addr {
		t.Fatalf("on %s after the avoidance; want the recommended server back", got)
	}
}

// Failures that are not the server's never move it: no network, the
// account or its pass, a refused port, a cancellation.
func TestFailuresThatAreNotTheServersDoNotSwitch(t *testing.T) {
	notTheServer := []error{
		ErrNoNetwork,
		&net.DNSError{Err: "no such host", Name: "a.example"},
		context.Canceled,
		fmt.Errorf("rebuilding: %w", errRebuildCoolingDown),
		ErrNoUsableSession,
		fxa.ErrReauthRequired,
		&guardian.HTTPError{Operation: "pass", StatusCode: http.StatusUnauthorized},
		&guardian.HTTPError{Operation: "pass", StatusCode: http.StatusForbidden},
		&guardian.HTTPError{Operation: "pass", StatusCode: http.StatusTooManyRequests},
		&guardian.HTTPError{Operation: "pass", StatusCode: http.StatusUnavailableForLegalReasons},
		&guardian.HTTPError{Operation: "pass", StatusCode: http.StatusBadGateway},
		&accounts.NoUsableAccountError{},
		&proxyConnectHTTPError{statusCode: http.StatusUnauthorized, status: "401"},
		&proxyConnectHTTPError{statusCode: http.StatusForbidden, status: "403"},
		&proxyConnectHTTPError{statusCode: http.StatusProxyAuthRequired, status: "407"},
		&proxyConnectHTTPError{statusCode: http.StatusTooManyRequests, status: "429"},
		&LocationRefusedError{Err: &proxyConnectHTTPError{statusCode: http.StatusForbidden, status: "403"}},
	}
	for _, err := range notTheServer {
		if serverFault(err) {
			t.Errorf("%v counted against the server", err)
		}
	}
	theServer := []error{
		errServerReset,
		errProxySessionUnhealthy,
		fmt.Errorf("%w: %w", errProxySessionUnhealthy, &tunnelOpenTimeoutError{timeout: time.Second}),
		fmt.Errorf("%w: %w", errProxySessionUnhealthy, &proxyConnectHTTPError{statusCode: http.StatusBadGateway, status: "502"}),
		io.EOF,
		context.DeadlineExceeded,
	}
	for _, err := range theServer {
		if !serverFault(err) {
			t.Errorf("%v not counted against the server", err)
		}
	}

	t.Run("no network", func(t *testing.T) {
		noRedialWait(t)
		f := newFailoverFixture(t, map[string]error{serverA: ErrNoNetwork})
		f.withGuardian(t)
		for range 6 {
			if _, err := f.request(); err == nil {
				t.Fatal("no network: the tunnel fails")
			}
		}
		for _, addr := range f.dials() {
			if addr != serverA {
				t.Fatalf("dialed %v", f.dials())
			}
		}
		if len(f.dials()) < 6 || f.c.currentServer().Addr != serverA || f.failover.Avoided(serverA) || f.persisted(t) != serverA {
			t.Fatalf("a network failure moved the server: dialed %v", f.dials())
		}
	})
	t.Run("refused pass", func(t *testing.T) {
		f := newFailoverFixture(t, nil)
		refused := &proxyConnectHTTPError{statusCode: http.StatusUnauthorized, status: "401 Unauthorized"}
		f.c.current.session = &fakeProxySession{openErr: refused}
		// No auth: every new pass fails before a session is dialed.
		for range 4 {
			f.c.renewMu.Lock()
			f.c.passBackoff.reset()
			f.c.renewMu.Unlock()
			if _, err := f.c.OpenTunnel("example.com:443"); err == nil {
				t.Fatal("the pass is refused")
			}
		}
		if f.c.currentServer().Addr != serverA || f.failover.Avoided(serverA) || len(f.dials()) != 0 {
			t.Fatalf("a pass problem moved the server: dialed %v", f.dials())
		}
	})
	t.Run("refused port", func(t *testing.T) {
		f := newFailoverFixture(t, nil)
		f.c.current.session = &fakeProxySession{openErr: &proxyConnectHTTPError{statusCode: http.StatusBadGateway, status: "502 Bad Gateway"}}
		for range 4 {
			if _, err := f.c.OpenTunnel("example.com:22"); err == nil {
				t.Fatal("port 22 is refused")
			}
		}
		if f.c.currentServer().Addr != serverA || len(f.dials()) != 0 {
			t.Fatalf("a refused port rebuilt or moved: dialed %v", f.dials())
		}
	})
}

// When every server of the location fails, the upstream goes through them
// (the same city first) and then stays in the location: another country is
// never tried.
func TestEveryServerFailingKeepsTheLocation(t *testing.T) {
	noRedialWait(t)
	down := map[string]error{serverA: errServerReset, serverB: errServerReset, serverC: errServerReset, "fr.example:2499": errServerReset}
	f := newFailoverFixture(t, down)
	f.withGuardian(t)
	for range 12 {
		if _, err := f.request(); err == nil {
			t.Fatal("every server is down")
		}
	}
	var order []string
	for _, addr := range f.dials() {
		if addr == "fr.example:2499" {
			t.Fatalf("another country was tried: %v", f.dials())
		}
		if len(order) == 0 || order[len(order)-1] != addr {
			order = append(order, addr)
		}
	}
	if got, want := fmt.Sprint(order), fmt.Sprint([]string{serverA, serverB, serverC}); got != want {
		t.Fatalf("servers tried %s, want %s", got, want)
	}
	if got := f.c.currentServer().Addr; got != serverC {
		t.Fatalf("stays on %s, want %s", got, serverC)
	}
	for _, addr := range []string{serverA, serverB, serverC} {
		if !f.failover.Avoided(addr) {
			t.Fatalf("%s not avoided", addr)
		}
	}
}

// An avoided server is skipped by the failover and by selection until its
// time is up; then it is chosen again.
func TestAvoidedServerIsSkippedUntilItsTimeIsUp(t *testing.T) {
	clock := time.Now()
	f := NewServerFailover(filepath.Join(t.TempDir(), "selection.json"))
	f.now = func() time.Time { return clock }
	countries := failoverCountries()
	location := LocationCandidates(countries, "DE")
	a, b := location[0], location[1]

	fail := func(server Candidate) (Candidate, bool) {
		t.Helper()
		var next Candidate
		var ok bool
		for i := 1; i <= serverFailoverStrikes; i++ {
			next, ok = f.Failed(location, nil, server, errServerReset)
			if ok != (i == serverFailoverStrikes) {
				t.Fatalf("failure %d of %s: switched=%v", i, server.Addr, ok)
			}
		}
		return next, ok
	}
	if next, _ := fail(a); next.Addr != serverB {
		t.Fatalf("after A: %s, want B", next.Addr)
	}
	// Selection skips A while it is avoided, also as the persisted choice.
	if err := SaveSelection(f.selectionFile, a); err != nil {
		t.Fatal(err)
	}
	for range 20 {
		got, fromState, err := ResolveWithStateAndCountry("", "DE", countries, f.selectionFile, f.Avoided)
		if err != nil || fromState || got.Addr != serverB {
			t.Fatalf("while A is avoided: %s fromState=%v err=%v", got.Addr, fromState, err)
		}
	}
	// B fails too: the next is Frankfurt, not A.
	if next, _ := fail(b); next.Addr != serverC {
		t.Fatalf("after B: %s, want C", next.Addr)
	}

	clock = clock.Add(serverAvoidTime - time.Second)
	if !f.Avoided(serverA) {
		t.Fatal("A is avoided until its time is up")
	}
	clock = clock.Add(time.Second)
	if f.Avoided(serverA) {
		t.Fatal("A's time is up")
	}
	if err := SaveSelection(f.selectionFile, a); err != nil {
		t.Fatal(err)
	}
	got, fromState, err := ResolveWithStateAndCountry("", "DE", countries, f.selectionFile, f.Avoided)
	if err != nil || !fromState || got.Addr != serverA {
		t.Fatalf("A is back: %s fromState=%v err=%v", got.Addr, fromState, err)
	}
	// C fails: Berlin's A is back in the choice (B's time is up too).
	if next, _ := fail(location[2]); next.Addr != serverA && next.Addr != serverB {
		t.Fatalf("after C: %s, want a Berlin server", next.Addr)
	}
	if persisted, _ := loadProxySelection(f.selectionFile); persisted.CityCode != "ber" {
		t.Fatalf("persisted %+v, want the Berlin server", persisted)
	}
}

// The recommended location fails over among its own servers.
func TestRecommendedLocationFailsOverWithinItself(t *testing.T) {
	countries := append(failoverCountries(), serverlist.Country{
		Name: "Recommended", Code: serverlist.RecommendedCountryCode, Cities: []serverlist.City{
			{Name: "Anycast", Code: "any", Servers: []serverlist.Server{{Hostname: "rec1.example", Port: 2499}, {Hostname: "rec2.example", Port: 2499}}},
		},
	})
	location := LocationCandidates(countries, "")
	if len(location) != 2 || !location[0].IsRecommended() || !location[1].IsRecommended() {
		t.Fatalf("recommended location %v", location)
	}
	f := NewServerFailover("")
	var next Candidate
	for range serverFailoverStrikes {
		next, _ = f.Failed(location, nil, location[0], errServerReset)
	}
	if next.Addr != "rec2.example:2499" {
		t.Fatalf("next %q, want the other recommended server", next.Addr)
	}
}
