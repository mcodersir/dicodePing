package proxy

import (
	"context"
	"crypto/x509"
	"errors"
	"fmt"
	"net"
	"net/http"
	"sync"
	"sync/atomic"
	"time"
)

const (
	maxDistinctOpenTimeoutTargets = 3
	maxDistinctBadGatewayTargets  = 3
)

var (
	errProxySessionUnhealthy = errors.New("upstream proxy session became unhealthy")
	ErrNoUsableSession       = errors.New("no usable upstream proxy session")
)

// upstreamRoots replaces the system certificate roots for upstream TLS
// (H2 and H3) when set. Only tests set it, to trust a local fixture server;
// hostname and certificate-chain validation stay on.
var upstreamRoots atomic.Pointer[x509.CertPool]

// SetUpstreamRoots makes upstream sessions trust only pool (nil restores
// the system roots). It exists for tests in other packages that run a
// local upstream fixture.
func SetUpstreamRoots(pool *x509.CertPool) { upstreamRoots.Store(pool) }

type tunnelOpener interface {
	OpenTunnel(authority string) (net.Conn, error)
}

// clientAffinityTunnelOpener keeps a client's tunnels on one upstream session
// when the implementation can provide session affinity.
type clientAffinityTunnelOpener interface {
	OpenTunnelForClient(authority, clientKey string) (net.Conn, error)
}

type proxySessionTokenUpdater interface {
	UpdateToken(token string) error
}

// proxySessionLivenessChecker is implemented by sessions that can report
// whether their underlying connection is still usable, so a silently dead
// session is skipped before a client connection is bound to it.
type proxySessionLivenessChecker interface {
	IsAlive() bool
}

// isSessionAlive reports whether session can still carry new tunnels.
// Sessions that cannot answer are assumed alive, keeping the reactive
// rebuild path as the fallback.
func isSessionAlive(session proxySession) bool {
	if session == nil {
		return false
	}
	if checker, ok := session.(proxySessionLivenessChecker); ok {
		return checker.IsAlive()
	}
	return true
}

type sessionFailureTracker struct {
	mu                 sync.Mutex
	openTimeoutTargets map[string]struct{}
	badGatewayTargets  map[string]struct{}
}

// upstreamPorts are the destination ports Mozilla's proxy connects to. It
// answers CONNECT to any other port with 502 Bad Gateway, which says
// nothing about the session (measured 2026-10-10 through the tunnel: 80,
// 443, 8080, and 8443 open; 21, 22, 25, 53, 81, 110, 143, 465, 587, 853,
// 993, 995, 1080, 2052-2096, 3000, 3128, 3389, 4443, 5000, 5222, 7443,
// 8000, 8008, 8081, 8088, 8444, 8880, 8888, 9000, 9090, 9443, 9898, and
// 10443 refused). Nothing is refused locally: this only explains a 502.
var upstreamPorts = map[string]bool{"80": true, "443": true, "8080": true, "8443": true}

// UpstreamPortsText lists upstreamPorts for messages.
const UpstreamPortsText = "80, 443, 8080, and 8443"

// PortAllowed reports whether Mozilla's proxy connects to port.
func PortAllowed(port string) bool { return upstreamPorts[port] }

// portRefused reports whether err is Mozilla's proxy refusing the port of
// authority rather than a failure of the session or the destination.
func portRefused(authority string, err error) bool {
	var connectErr *proxyConnectHTTPError
	if !errors.As(err, &connectErr) || connectErr.statusCode != http.StatusBadGateway {
		return false
	}
	_, port, splitErr := net.SplitHostPort(authority)
	return splitErr == nil && !upstreamPorts[port]
}

func (t *sessionFailureTracker) observe(authority string, err error) error {
	if portRefused(authority, err) {
		// A refused port neither shows a sick session nor a healthy one.
		return err
	}
	if err == nil {
		t.mu.Lock()
		t.openTimeoutTargets = nil
		t.badGatewayTargets = nil
		t.mu.Unlock()
		return nil
	}

	var timeoutErr *tunnelOpenTimeoutError
	var connectErr *proxyConnectHTTPError
	t.mu.Lock()
	defer t.mu.Unlock()
	switch {
	case errors.As(err, &timeoutErr):
		if t.openTimeoutTargets == nil {
			t.openTimeoutTargets = make(map[string]struct{})
		}
		t.openTimeoutTargets[authority] = struct{}{}
		t.badGatewayTargets = nil
		if len(t.openTimeoutTargets) >= maxDistinctOpenTimeoutTargets {
			return fmt.Errorf("%w: %w", errProxySessionUnhealthy, err)
		}
	case errors.As(err, &connectErr) && connectErr.statusCode == http.StatusBadGateway:
		if t.badGatewayTargets == nil {
			t.badGatewayTargets = make(map[string]struct{})
		}
		t.badGatewayTargets[authority] = struct{}{}
		t.openTimeoutTargets = nil
		if len(t.badGatewayTargets) >= maxDistinctBadGatewayTargets {
			return fmt.Errorf("%w: %w", errProxySessionUnhealthy, err)
		}
	default:
		t.openTimeoutTargets = nil
		t.badGatewayTargets = nil
	}
	return err
}

type proxySession interface {
	tunnelOpener
	Close() error
}

type tunnelOpenTimeoutError struct {
	timeout time.Duration
}

func (e *tunnelOpenTimeoutError) Error() string {
	return fmt.Sprintf("proxy CONNECT timed out after %s", e.timeout)
}

func (e *tunnelOpenTimeoutError) Timeout() bool {
	return true
}

func (e *tunnelOpenTimeoutError) Temporary() bool {
	return true
}

type proxyConnectHTTPError struct {
	statusCode int
	status     string
	body       string
}

func (e *proxyConnectHTTPError) Error() string {
	if e.body == "" {
		return fmt.Sprintf("proxy CONNECT failed: %s", e.status)
	}
	return fmt.Sprintf("proxy CONNECT failed: %s: %s", e.status, e.body)
}

// Redacted is the error without the response body, for logs that are not
// verbose.
func (e *proxyConnectHTTPError) Redacted() string {
	sanitized := *e
	if sanitized.body != "" {
		sanitized.body = "<redacted; use -verbose>"
	}
	return sanitized.Error()
}

func shouldRebuildProxySession(err error) bool {
	if errors.Is(err, errSessionSaturated) {
		return false
	}
	if errors.Is(err, errProxySessionUnhealthy) {
		return true
	}
	var connectErr *proxyConnectHTTPError
	if errors.As(err, &connectErr) {
		switch connectErr.statusCode {
		case http.StatusUnauthorized, http.StatusForbidden, http.StatusProxyAuthRequired:
			return true
		default:
			return false
		}
	}
	var timeoutErr *tunnelOpenTimeoutError
	if errors.As(err, &timeoutErr) {
		return false
	}
	return true
}

type roundTripResult struct {
	resp *http.Response
	err  error
}

func roundTripWithOpenTimeout(timeout time.Duration, do func(context.Context) (*http.Response, error)) (*http.Response, context.CancelFunc, error) {
	ctx, cancel := context.WithCancel(context.Background())
	if timeout <= 0 {
		resp, err := do(ctx)
		if err != nil {
			cancel()
			return nil, nil, err
		}
		return resp, cancel, nil
	}

	resultCh := make(chan roundTripResult, 1)
	go func() {
		resp, err := do(ctx)
		resultCh <- roundTripResult{resp: resp, err: err}
	}()

	timer := time.NewTimer(timeout)
	select {
	case result := <-resultCh:
		if !timer.Stop() {
			select {
			case <-timer.C:
			default:
			}
		}
		if result.err != nil {
			cancel()
			return nil, nil, result.err
		}
		return result.resp, cancel, nil
	case <-timer.C:
		cancel()
		go func() {
			cleanupTimer := time.NewTimer(timeout)
			defer cleanupTimer.Stop()
			select {
			case result := <-resultCh:
				if result.resp != nil && result.resp.Body != nil {
					_ = result.resp.Body.Close()
				}
			case <-cleanupTimer.C:
			}
		}()
		return nil, nil, &tunnelOpenTimeoutError{timeout: timeout}
	}
}
