package proxy

import (
	"context"
	"errors"
	"net/http"
	"testing"
	"time"
)

func TestRoundTripWithOpenTimeout(t *testing.T) {
	t.Parallel()

	_, _, err := roundTripWithOpenTimeout(20*time.Millisecond, func(ctx context.Context) (*http.Response, error) {
		<-ctx.Done()
		return nil, ctx.Err()
	})
	var timeoutErr *tunnelOpenTimeoutError
	if !errors.As(err, &timeoutErr) {
		t.Fatalf("expected tunnelOpenTimeoutError, got %v", err)
	}
}

func TestShouldRebuildProxySession(t *testing.T) {
	t.Parallel()

	if shouldRebuildProxySession(&proxyConnectHTTPError{statusCode: http.StatusBadGateway, status: "502 Bad Gateway"}) {
		t.Fatal("expected target/proxy CONNECT 502 to avoid session rebuild")
	}
	if !shouldRebuildProxySession(&proxyConnectHTTPError{statusCode: http.StatusProxyAuthRequired, status: "407 Proxy Authentication Required"}) {
		t.Fatal("expected proxy auth failure to rebuild session")
	}
	if shouldRebuildProxySession(&tunnelOpenTimeoutError{timeout: time.Second}) {
		t.Fatal("expected CONNECT timeout to avoid session rebuild")
	}
	if !shouldRebuildProxySession(errors.New("transport closed")) {
		t.Fatal("expected transport errors to rebuild session")
	}
}

func TestSessionFailureTrackerRequiresDistinctTargets(t *testing.T) {
	t.Parallel()

	tracker := &sessionFailureTracker{}
	timeoutErr := &tunnelOpenTimeoutError{timeout: time.Second}
	for i := 0; i < 5; i++ {
		if err := tracker.observe("same.example:443", timeoutErr); errors.Is(err, errProxySessionUnhealthy) {
			t.Fatal("repeated failure for one target should not retire the session")
		}
	}
	if err := tracker.observe("second.example:443", timeoutErr); errors.Is(err, errProxySessionUnhealthy) {
		t.Fatal("two failed targets should not retire the session")
	}
	if err := tracker.observe("third.example:443", timeoutErr); !errors.Is(err, errProxySessionUnhealthy) {
		t.Fatalf("expected three distinct timeout targets to retire the session, got %v", err)
	}

	tracker.observe("healthy.example:443", nil)
	badGateway := &proxyConnectHTTPError{statusCode: http.StatusBadGateway, status: "502 Bad Gateway"}
	if err := tracker.observe("one.example:443", badGateway); errors.Is(err, errProxySessionUnhealthy) {
		t.Fatal("one 502 target should not retire the session")
	}
	if err := tracker.observe("two.example:443", badGateway); errors.Is(err, errProxySessionUnhealthy) {
		t.Fatal("two 502 targets should not retire the session")
	}
	if err := tracker.observe("three.example:443", badGateway); !errors.Is(err, errProxySessionUnhealthy) {
		t.Fatalf("expected three distinct 502 targets to retire the session, got %v", err)
	}
}

// Mozilla's proxy answers 502 for ports it does not connect to; such
// answers neither retire the session nor reset the count of real failures.
func TestRefusedPortDoesNotRetireSession(t *testing.T) {
	t.Parallel()

	tracker := &sessionFailureTracker{}
	badGateway := &proxyConnectHTTPError{statusCode: http.StatusBadGateway, status: "502 Bad Gateway"}
	for _, target := range []string{"a.example:9898", "b.example:22", "c.example:3000", "203.0.113.5:81", "[2001:db8::1]:8000"} {
		if !portRefused(target, badGateway) {
			t.Fatalf("%s: expected a refused port", target)
		}
		if err := tracker.observe(target, badGateway); errors.Is(err, errProxySessionUnhealthy) {
			t.Fatalf("%s: a refused port must not retire the session", target)
		}
	}
	for _, target := range []string{"web.example:80", "web.example:443", "web.example:8080", "web.example:8443"} {
		if portRefused(target, badGateway) {
			t.Fatalf("%s: a web port is not refused by policy", target)
		}
	}
	if portRefused("a.example:9898", &proxyConnectHTTPError{statusCode: http.StatusForbidden}) {
		t.Fatal("only 502 means a refused port")
	}

	tracker.observe("one.example:443", badGateway)
	tracker.observe("two.example:443", badGateway)
	tracker.observe("other.example:9898", badGateway)
	if err := tracker.observe("three.example:443", badGateway); !errors.Is(err, errProxySessionUnhealthy) {
		t.Fatalf("a refused port in between must not reset real failures, got %v", err)
	}
}
