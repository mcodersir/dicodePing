package proxy

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net"
	"os"
	"testing"
	"time"

	"dicodeping/fox/internal/accounts"
	"dicodeping/fox/internal/fxa"
	"dicodeping/fox/internal/guardian"
	"dicodeping/fox/internal/netstate"
)

func TestFailureCode(t *testing.T) {
	dial := func(err error) error {
		return &net.OpError{Op: "dial", Net: "tcp", Err: &os.SyscallError{Syscall: "connect", Err: err}}
	}
	refused := dial(errors.New("refused"))
	if c, err := net.DialTimeout("tcp", "127.0.0.1:1", time.Second); err == nil {
		_ = c.Close()
	} else {
		refused = err // the real "connection refused" of this system
	}
	cases := []struct {
		name string
		err  error
		want string
	}{
		{"nil", nil, ""},
		{"reauth", fmt.Errorf("renewing: %w", fxa.ErrReauthRequired), FailureSignIn},
		{"quota", &passQuotaError{}, FailureQuota},
		{"quota 429", &guardian.HTTPError{Operation: "pass", StatusCode: 429}, FailureQuota},
		{"not entitled", &guardian.HTTPError{Operation: "pass", StatusCode: 403}, FailureNotEntitled},
		{"region", &guardian.HTTPError{Operation: "pass", StatusCode: 451}, FailureRegion},
		{"guardian 502", &guardian.HTTPError{Operation: "pass", StatusCode: 502}, FailureServer},
		{"no account", &accounts.NoUsableAccountError{Summary: "1 used up"}, FailureNoAccount},
		{"connect 403", &proxyConnectHTTPError{statusCode: 403, status: "403 Forbidden"}, FailureRefused},
		{"chosen location refused", fmt.Errorf("tunnel: %w", &LocationRefusedError{Err: &proxyConnectHTTPError{statusCode: 403, status: "403 Forbidden"}}), FailureLocationRefused},
		{"rebuild cooling after a refusal", fmt.Errorf("%w for 9s: %w", errRebuildCoolingDown, &proxyConnectHTTPError{statusCode: 401, status: "401"}), FailureRefused},
		{"rebuild cooling after a timeout", fmt.Errorf("%w for 9s: %w", errRebuildCoolingDown, &tunnelOpenTimeoutError{timeout: time.Second}), FailureUnreachable},
		{"dns", fmt.Errorf("pass: %w", &net.DNSError{Err: "no such host", Name: "vpn.mozilla.org", IsNotFound: true}), FailureNoNetwork},
		{"refused", refused, FailureUnreachable},
		{"tunnel timeout", &tunnelOpenTimeoutError{timeout: time.Second}, FailureUnreachable},
		{"deadline", context.DeadlineExceeded, FailureUnreachable},
		{"eof", fmt.Errorf("tls handshake: %w", io.EOF), FailureUnreachable},
		{"other", errors.New("something new"), FailureOther},
	}
	for _, tc := range cases {
		if got := FailureCode(tc.err); got != tc.want {
			t.Errorf("%s: FailureCode(%v) = %q, want %q", tc.name, tc.err, got, tc.want)
		}
	}
	for _, e := range noNetworkErrnos {
		if got := FailureCode(dial(e)); got != FailureNoNetwork {
			t.Errorf("errno %d: got %q, want %q", e, got, FailureNoNetwork)
		}
	}
}

// A rebuild that failed for want of a network does not space the next one;
// RetryNow forgets the spacing.
func TestRebuildBackoffAndTheNetwork(t *testing.T) {
	noRoute := &net.OpError{Op: "dial", Net: "tcp", Err: &os.SyscallError{Syscall: "connect", Err: noNetworkErrnos[0]}}
	now := time.Now()
	var b rebuildBackoff
	b.record(now, nil, noRoute)
	if w := b.wait(newPassSteps, now); w > 0 {
		t.Fatalf("a failure without a network waits %s", w)
	}
	b.record(now, nil, context.DeadlineExceeded)
	if w := b.wait(newPassSteps, now); w <= 0 {
		t.Fatal("a failure at Mozilla must space the next rebuild")
	}
	c := &Controller{}
	c.passBackoff.record(now, nil, context.DeadlineExceeded)
	c.lastRenewalErr, c.nextAttemptAt = noRoute, now.Add(time.Hour)
	c.RetryNow()
	if w := c.passBackoff.wait(newPassSteps, now); w > 0 || !c.nextAttemptAt.IsZero() {
		t.Fatalf("after RetryNow: wait %s, next attempt %s", w, c.nextAttemptAt)
	}
}

// While the phone reports no network, a tunnel failure rebuilds nothing:
// it fails at once as no network, asking Guardian nothing.
func TestNoRebuildWithoutANetwork(t *testing.T) {
	netstate.Report(false)
	t.Cleanup(func() { netstate.Report(true) })
	c := &Controller{}
	err := c.rebuildSession(nil, errors.New("tunnel failed"))
	if !errors.Is(err, ErrNoNetwork) || FailureCode(err) != FailureNoNetwork {
		t.Fatalf("got %v (%s)", err, FailureCode(err))
	}
	if !c.passBackoff.lastAt.IsZero() || !c.redialBackoff.lastAt.IsZero() {
		t.Fatal("a rebuild was attempted without a network")
	}
}

func TestSessionReplaced(t *testing.T) {
	if !SessionReplaced(`Get "https://www.google.com/generate_204": http2: client connection force closed via ClientConn.Close`) {
		t.Fatal("a closed HTTP/2 session not recognized")
	}
	if SessionReplaced("dial tcp: i/o timeout") {
		t.Fatal("a timeout taken for a replaced session")
	}
}
