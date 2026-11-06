package proxy

import (
	"errors"
	"net/http"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"dicodeping/fox/internal/fxa"
	"dicodeping/fox/internal/guardian"
)

// rebuildController has one session that fails with openErr and a factory
// that records the passes it dials with. It has no auth, so any attempt to
// get a new pass fails with "no refresh token available".
func rebuildController(openErr error, validFor time.Duration) (*Controller, func() []string) {
	var mu sync.Mutex
	var dialed []string
	c := &Controller{
		current: &managedSession{
			session:   &fakeProxySession{openErr: openErr},
			rawToken:  "pass-1",
			expiresAt: time.Now().Add(validFor),
			accepting: true,
		},
		sessionFactory: func(token string) (proxySession, error) {
			mu.Lock()
			dialed = append(dialed, token)
			mu.Unlock()
			return &fakeProxySession{}, nil
		},
	}
	return c, func() []string {
		mu.Lock()
		defer mu.Unlock()
		return append([]string(nil), dialed...)
	}
}

// A dead connection is dialed again with the pass it had; Guardian is not
// asked for a new one.
func TestDeadConnectionRedialsWithThePass(t *testing.T) {
	c, dialed := rebuildController(errors.New("connection reset by peer"), time.Hour)
	conn, err := c.OpenTunnel("example.com:443")
	if err != nil {
		t.Fatalf("OpenTunnel: %v", err)
	}
	_ = conn.Close()
	if got := dialed(); len(got) != 1 || got[0] != "pass-1" {
		t.Fatalf("dialed %v, want one redial with pass-1", got)
	}
	if c.passBackoff.streak.Load() != 0 || !c.passBackoff.lastAt.IsZero() {
		t.Fatal("a redial must not count as a new pass")
	}
}

// A pass about to expire is not redialed: a new pass is due anyway.
func TestExpiringPassIsNotRedialed(t *testing.T) {
	c, dialed := rebuildController(errors.New("connection reset by peer"), time.Minute)
	_, err := c.OpenTunnel("example.com:443")
	if err == nil || !strings.Contains(err.Error(), "no refresh token") {
		t.Fatalf("want the new pass attempt's error, got %v", err)
	}
	if got := dialed(); len(got) != 0 {
		t.Fatalf("dialed %v with an expiring pass", got)
	}
}

// A refused pass (CONNECT 401) gets one new pass attempt; the next ones
// wait (10 s, then longer), and the wait carries the reason.
func TestNewPassRebuildsBackOff(t *testing.T) {
	refused := &proxyConnectHTTPError{statusCode: http.StatusUnauthorized, status: "401 Unauthorized"}
	c, dialed := rebuildController(refused, time.Hour)
	_, err := c.OpenTunnel("example.com:443")
	if !errors.Is(err, errRebuildCoolingDown) || !strings.Contains(err.Error(), "no refresh token") {
		t.Fatalf("want a cooling-down error carrying the failed attempt, got %v", err)
	}
	if n := c.passBackoff.streak.Load(); n != 1 {
		t.Fatalf("%d new pass attempts, want 1", n)
	}
	if got := dialed(); len(got) != 0 {
		t.Fatalf("a refused pass was redialed: %v", got)
	}
	// After the wait, one more attempt; the one after it waits 30 s.
	c.passBackoff.lastAt = time.Now().Add(-11 * time.Second)
	if _, err := c.OpenTunnel("example.com:443"); !errors.Is(err, errRebuildCoolingDown) {
		t.Fatalf("want cooling down after the second attempt, got %v", err)
	}
	if n := c.passBackoff.streak.Load(); n != 2 {
		t.Fatalf("%d new pass attempts, want 2", n)
	}
	if wait := c.passBackoff.wait(newPassSteps, time.Now()); wait < 25*time.Second || wait > 30*time.Second {
		t.Fatalf("third attempt waits %s, want about 30 s", wait)
	}

	// A tunnel that opens resets the streak.
	c.passBackoff.opened()
	if n := c.passBackoff.streak.Load(); n != 0 {
		t.Fatalf("streak %d after a tunnel opened", n)
	}
}

// A CONNECT 403 gets one new pass; a 403 with that pass is the location's
// or the destination's answer: the client gets it, no further pass is
// fetched, and the session keeps serving.
func TestRefusalAfterANewPassPassesThrough(t *testing.T) {
	forbidden := &proxyConnectHTTPError{statusCode: http.StatusForbidden, status: "403 Forbidden"}
	c := &Controller{
		current: &managedSession{
			session:   &fakeProxySession{openErr: forbidden},
			rawToken:  "pass-1",
			expiresAt: time.Now().Add(time.Hour),
			accepting: true,
		},
	}
	var passes atomic.Int32
	c.refreshSession = func() error {
		passes.Add(1)
		c.swapSession(&fakeProxySession{openErr: forbidden}, "pass-2", time.Now().Add(time.Hour))
		return nil
	}
	for range 3 {
		_, err := c.OpenTunnel("locked.example:443")
		var connectErr *proxyConnectHTTPError
		if !errors.As(err, &connectErr) || connectErr.statusCode != http.StatusForbidden {
			t.Fatalf("want the 403, got %v", err)
		}
	}
	if n := passes.Load(); n != 1 {
		t.Fatalf("%d new passes, want 1", n)
	}
	c.mu.Lock()
	accepting, after := c.current.accepting, c.current.afterRefusal
	c.mu.Unlock()
	if !accepting || !after {
		t.Fatalf("accepting=%v afterRefusal=%v, want both", accepting, after)
	}

	// A renewed pass gets a fresh chance.
	if err := c.updateCurrentSessionToken("pass-3", time.Now().Add(time.Hour)); err != nil {
		t.Skipf("the fake session takes no token update: %v", err)
	}
	if c.current.afterRefusal {
		t.Fatal("a renewed pass must clear afterRefusal")
	}
}

// refusingController has a session that refuses every CONNECT with status;
// each new pass gets a session that refuses it too.
func refusingController(status int, chosen bool) (*Controller, *atomic.Int32) {
	refused := &proxyConnectHTTPError{statusCode: status, status: http.StatusText(status)}
	c := &Controller{
		chosenLocation: chosen,
		current: &managedSession{
			session:   &fakeProxySession{openErr: refused},
			rawToken:  "pass-1",
			expiresAt: time.Now().Add(time.Hour),
			accepting: true,
		},
	}
	var passes atomic.Int32
	c.refreshSession = func() error {
		passes.Add(1)
		c.swapSession(&fakeProxySession{openErr: refused}, "pass-2", time.Now().Add(time.Hour))
		return nil
	}
	return c, &passes
}

// A location the user chose whose server refuses the CONNECT (403 or 407)
// again with a new pass is reported as location_refused; the recommended
// or the fastest location keeps the plain refusal.
func TestRefusedChosenLocationIsLocationRefused(t *testing.T) {
	for _, status := range []int{http.StatusForbidden, http.StatusProxyAuthRequired} {
		c, passes := refusingController(status, true)
		_, err := c.OpenTunnel("www.google.com:443")
		var locationErr *LocationRefusedError
		var connectErr *proxyConnectHTTPError
		if !errors.As(err, &locationErr) || !errors.As(err, &connectErr) || connectErr.statusCode != status {
			t.Fatalf("HTTP %d: want a LocationRefusedError carrying the refusal, got %v", status, err)
		}
		if FailureCode(err) != FailureLocationRefused || !strings.Contains(err.Error(), "does not let this account use this location") {
			t.Fatalf("HTTP %d: code %q, text %q", status, FailureCode(err), err)
		}
		if n := passes.Load(); n != 1 {
			t.Fatalf("HTTP %d: %d new passes, want 1", status, n)
		}

		c, _ = refusingController(status, false)
		_, err = c.OpenTunnel("www.google.com:443")
		if errors.As(err, &locationErr) || FailureCode(err) != FailureRefused {
			t.Fatalf("HTTP %d, not a chosen location: want refused, got %q (%v)", status, FailureCode(err), err)
		}
	}
}

// While the renewal loop waits after a failure, client tunnels do not ask
// Guardian for a pass either.
func TestNewPassWaitsForTheRenewalLoop(t *testing.T) {
	c, _ := rebuildController(nil, time.Hour)
	c.current.accepting = false
	c.recordRenewalOutcome(fxa.ErrReauthRequired, time.Now().Add(15*time.Minute))
	_, err := c.OpenTunnel("example.com:443")
	if !errors.Is(err, errRebuildCoolingDown) || !errors.Is(err, fxa.ErrReauthRequired) {
		t.Fatalf("want a wait carrying the renewal's error, got %v", err)
	}
	if !c.passBackoff.lastAt.IsZero() {
		t.Fatal("no pass may be requested while the renewal loop waits")
	}
}

func TestWakeRetryDelay(t *testing.T) {
	now := time.Now()
	transient := errors.New("dial tcp: i/o timeout")
	want := []time.Duration{10 * time.Second, 20 * time.Second, 40 * time.Second, 80 * time.Second, 2 * time.Minute, 2 * time.Minute, 2 * time.Minute}
	for i, w := range want {
		if got := WakeRetryDelay(transient, i+1, now); got != w {
			t.Errorf("failure %d: %s, want %s", i+1, got, w)
		}
	}
	if LastingWakeFailure(transient, now) {
		t.Error("a timeout is not lasting")
	}
	region := &guardian.HTTPError{Operation: "pass", StatusCode: http.StatusUnavailableForLegalReasons}
	if got := WakeRetryDelay(region, 1, now); got != terminalRenewalRetryDelay || !LastingWakeFailure(region, now) {
		t.Errorf("region: %s, want %s and lasting", got, terminalRenewalRetryDelay)
	}
	busy := &guardian.HTTPError{Operation: "pass", StatusCode: http.StatusServiceUnavailable, RetryAfter: 10 * time.Minute}
	if got := WakeRetryDelay(busy, 1, now); got != 10*time.Minute {
		t.Errorf("Retry-After: %s, want 10m", got)
	}
}
