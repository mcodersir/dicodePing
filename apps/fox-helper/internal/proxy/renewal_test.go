package proxy

import (
	"errors"
	"fmt"
	"strings"
	"testing"
	"time"

	"dicodeping/fox/internal/fxa"
	"dicodeping/fox/internal/guardian"
)

func TestProxyControllerSleepOrDoneWakesOnClose(t *testing.T) {
	t.Parallel()

	controller := &Controller{done: make(chan struct{})}
	done := make(chan bool, 1)
	go func() {
		done <- controller.sleepOrDone(time.Hour)
	}()

	if err := controller.Close(); err != nil {
		t.Fatalf("Close returned error: %v", err)
	}

	select {
	case keptGoing := <-done:
		if keptGoing {
			t.Fatal("expected sleepOrDone to stop after Close")
		}
	case <-time.After(time.Second):
		t.Fatal("sleepOrDone did not wake after Close")
	}
}

func TestProxyControllerRenewWithTimeoutTimesOut(t *testing.T) {
	t.Parallel()

	controller := &Controller{done: make(chan struct{})}
	controller.renewMu.Lock()
	defer controller.renewMu.Unlock()

	timedOutCh := make(chan bool, 1)
	go func() {
		_, timedOut := controller.renewWithTimeout(20 * time.Millisecond)
		timedOutCh <- timedOut
	}()

	select {
	case timedOut := <-timedOutCh:
		if !timedOut {
			t.Fatal("expected renewWithTimeout to time out")
		}
	case <-time.After(time.Second):
		t.Fatal("renewWithTimeout did not return")
	}
}

func TestProxyControllerRenewWithTimeoutStopsWhenClosed(t *testing.T) {
	t.Parallel()

	controller := &Controller{done: make(chan struct{})}
	close(controller.done)

	_, timedOut := controller.renewWithTimeout(time.Hour)
	if timedOut {
		t.Fatal("expected closed controller not to report renewal timeout")
	}
}

func TestRenewalRetryDelayBacksOffTerminalFailures(t *testing.T) {
	now := time.Date(2026, 10, 9, 12, 0, 0, 0, time.UTC)
	reset := now.Add(2 * time.Hour)
	tests := []struct {
		name string
		err  error
		want time.Duration
		code string
	}{
		{"transient", errors.New("connection reset"), proxyPassRetryDelay, "renewal_failed"},
		{"reauth", fmt.Errorf("refresh: %w", fxa.ErrReauthRequired), terminalRenewalRetryDelay, "reauth_required"},
		{"region", fmt.Errorf("x: %w", guardian.ErrRegionUnavailable), terminalRenewalRetryDelay, "region_unavailable"},
		{"quota with reset", &passQuotaError{usage: &guardian.ProxyUsage{Limit: 1, Reset: reset}}, 2*time.Hour + time.Minute, "quota_exhausted"},
	}
	for _, tc := range tests {
		if got := RenewalRetryDelay(tc.err, now); got != tc.want {
			t.Errorf("%s: delay %s, want %s", tc.name, got, tc.want)
		}
		if got := renewalFailureCode(tc.err); got != tc.code {
			t.Errorf("%s: code %q, want %q", tc.name, got, tc.code)
		}
	}
}

func TestProxyControllerRebuildCooldownAvoidsGuardianStorm(t *testing.T) {
	t.Parallel()

	controller := &Controller{
		current: &managedSession{session: &fakeProxySession{}, expiresAt: time.Now().Add(10 * time.Minute)},
	}
	failed := controller.current
	controller.passBackoff.record(time.Now(), errors.New("CONNECT 401"), errors.New("previous rebuild failed"))

	err := controller.rebuildSession(failed, &proxyConnectHTTPError{statusCode: 401, status: "401 Unauthorized"})
	if !errors.Is(err, errRebuildCoolingDown) || !strings.Contains(err.Error(), "previous rebuild failed") {
		t.Fatalf("expected a cooldown error without contacting Guardian, got %v", err)
	}
}

func TestProxyControllerNextRenewalDelayHasFloorAfterRenewal(t *testing.T) {
	t.Parallel()

	controller := &Controller{
		current:       &managedSession{expiresAt: time.Now().Add(time.Minute)},
		lastRenewalAt: time.Now(),
	}
	if got := controller.nextRenewalDelay(); got < minRenewalInterval-time.Second {
		t.Fatalf("expected a renewal floor near %s, got %s", minRenewalInterval, got)
	}
}

// A replaced session is reported, so the daemon can test the connection;
// a failed or skipped rebuild is not.
func TestSessionRebuildIsReported(t *testing.T) {
	t.Parallel()

	rebuilt := make(chan struct{}, 2)
	controller := &Controller{
		current:          &managedSession{session: &fakeProxySession{}, expiresAt: time.Now().Add(10 * time.Minute)},
		refreshSession:   func() error { return nil },
		OnSessionRebuilt: func() { rebuilt <- struct{}{} },
	}
	if err := controller.rebuildSession(controller.current, errProxySessionUnhealthy); err != nil {
		t.Fatal(err)
	}
	select {
	case <-rebuilt:
	case <-time.After(2 * time.Second):
		t.Fatal("the rebuild was not reported")
	}

	controller.refreshSession = func() error { return errors.New("no pass") }
	if err := controller.rebuildSession(controller.current, errProxySessionUnhealthy); err == nil {
		t.Fatal("expected the failure")
	}
	select {
	case <-rebuilt:
		t.Fatal("a failed rebuild must not be reported")
	case <-time.After(50 * time.Millisecond):
	}
}
