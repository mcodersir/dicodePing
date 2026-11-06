package proxy

import (
	"context"
	"errors"
	"fmt"
	"net"
	"os"
	"sync/atomic"
	"time"

	"dicodeping/fox/internal/accounts"
	"dicodeping/fox/internal/fxa"
	"dicodeping/fox/internal/guardian"
	"dicodeping/fox/internal/logx"
	"dicodeping/fox/internal/netstate"
)

const (
	proxyPassRenewLead  = 2 * time.Minute
	proxyPassRetryDelay = 30 * time.Second
	PassRenewTimeout    = 2 * time.Minute

	// proxyPassRenewAbandonGrace is how long a timed-out, cancelled renewal
	// may take to unwind before the loop reports it as stuck (it then waits
	// for it; the process keeps running).
	proxyPassRenewAbandonGrace = 30 * time.Second

	// minRenewalInterval spaces successful renewals, so a pass that is
	// already due for renewal when it arrives cannot cause a tight loop.
	minRenewalInterval = 10 * time.Second

	// usageProbeBytes is the tunnel traffic after which the quota is read
	// before the next pass renewal (whose answer carries it too), while the
	// account is within quotaProbeMargin of its switch point.
	usageProbeBytes = 512 << 20

	// quotaProbeMargin is how close to its switch point (nearSwitch: the
	// switch threshold, with an account pool) the active account's usage,
	// as last read plus the tunnel traffic since then, must come for
	// traffic to read its quota early; farther away, the pass renewals'
	// quota is enough, as in Firefox, which reads it only with its passes.
	quotaProbeMargin = 5 << 30

	// wakeRetryFirst and wakeRetryMax bound WakeRetryDelay's growing wait.
	wakeRetryFirst = 10 * time.Second
	wakeRetryMax   = 2 * time.Minute
)

// Rebuilds that tunnel failures trigger arrive per client request, so they
// are spaced: the n-th rebuild of a kind in a row (no tunnel opened in
// between) waits the n-th step after the one before (the last step from
// then on). A redial only opens a connection to the proxy server; a new
// pass is a Guardian request, which Firefox makes only when a pass expires,
// so those wait longer and never come closer than 10 s; no wait is longer
// than 2 minutes, which a user still waits out.
var (
	redialSteps  = []time.Duration{0, 10 * time.Second, 30 * time.Second, time.Minute}
	newPassSteps = []time.Duration{10 * time.Second, 10 * time.Second, 30 * time.Second, time.Minute, 2 * time.Minute}
)

var errRebuildCoolingDown = errors.New("upstream session rebuild is cooling down")

// ErrNoNetwork: the device reported that no network is connected.
var ErrNoNetwork = &net.OpError{Op: "dial", Err: &os.SyscallError{Syscall: "connect", Err: noNetworkErrnos[0]}}

// rebuildBackoff spaces the rebuilds of one kind.
type rebuildBackoff struct {
	// streak counts the rebuilds since a tunnel last opened.
	streak atomic.Int32
	// Guarded by renewMu: the last rebuild, its error, and what caused it.
	lastAt    time.Time
	lastErr   error
	lastCause error
}

// wait is how long the next rebuild must wait with steps, or <= 0.
func (b *rebuildBackoff) wait(steps []time.Duration, now time.Time) time.Duration {
	if b.lastAt.IsZero() {
		return 0
	}
	n := int(b.streak.Load())
	return steps[min(n, len(steps)-1)] - now.Sub(b.lastAt)
}

func (b *rebuildBackoff) record(now time.Time, cause, err error) {
	// A rebuild that failed because this device had no network reached
	// nothing at Mozilla: it must not make the next one wait, or a phone
	// whose data was off for a moment would wait minutes once it is back.
	if err != nil && FailureCode(err) == FailureNoNetwork {
		return
	}
	b.streak.Add(1)
	b.lastAt, b.lastErr, b.lastCause = now, err, cause
}

// coolingDown is the error while the next rebuild waits; it carries why
// the last one failed, or what caused it.
func (b *rebuildBackoff) coolingDown(wait time.Duration) error {
	why := b.lastErr
	if why == nil {
		why = b.lastCause
	}
	return fmt.Errorf("%w for %s: %w", errRebuildCoolingDown, wait.Round(time.Second), why)
}

// reset forgets the rebuilds so far (renewMu is held).
func (b *rebuildBackoff) reset() {
	b.streak.Store(0)
	b.lastAt, b.lastErr, b.lastCause = time.Time{}, nil, nil
}

// opened resets the streak: a tunnel opened.
func (b *rebuildBackoff) opened() {
	if b.streak.Load() != 0 {
		b.streak.Store(0)
	}
}

// recordRenewalOutcome stores the result of a renewal attempt for the status
// file. A nil err clears the failure fields.
func (c *Controller) recordRenewalOutcome(err error, retryAt time.Time) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if err == nil {
		c.lastError = ""
		c.lastRenewalErr = nil
		c.nextAttemptAt = time.Time{}
		c.lastRenewalAt = time.Now()
		return
	}
	c.lastError = renewalFailureCode(err)
	c.lastRenewalErr = err
	c.nextAttemptAt = retryAt
}

// setUsage records a new quota reading of the active account; the tunnel
// traffic that nearSwitch adds to it starts again from zero.
func (c *Controller) setUsage(usage *guardian.ProxyUsage) {
	if usage == nil {
		return
	}
	c.mu.Lock()
	c.usage = usage
	c.trafficSinceReading.Store(0)
	c.mu.Unlock()
}

// renewalFailureCode maps a renewal error to a stable status-file code.
func renewalFailureCode(err error) string {
	switch {
	case errors.Is(err, fxa.ErrReauthRequired):
		return "reauth_required"
	case errors.Is(err, guardian.ErrRegionUnavailable):
		return "region_unavailable"
	case errors.Is(err, accounts.ErrNoUsableAccount):
		return "no_usable_account"
	case errors.Is(err, guardian.ErrQuotaExceeded):
		return "quota_exhausted"
	case errors.Is(err, guardian.ErrNotEntitled):
		return "not_entitled"
	case errors.Is(err, guardian.ErrTokenInvalid):
		return "token_rejected"
	case errors.Is(err, context.DeadlineExceeded):
		return "timeout"
	case errors.Is(err, guardian.ErrServer):
		return "guardian_server_error"
	}
	return "renewal_failed"
}

// RenewalRetryDelay decides when a failed renewal is attempted again.
// Failures that retrying cannot fix soon back off for a long time instead
// of polling Guardian every proxyPassRetryDelay; a spent quota waits for its
// announced reset.
func RenewalRetryDelay(err error, now time.Time) time.Duration {
	var noAccount *accounts.NoUsableAccountError
	if errors.As(err, &noAccount) {
		if noAccount.RetryAt.IsZero() {
			return terminalRenewalRetryDelay
		}
		return min(max(noAccount.RetryAt.Sub(now)+time.Second, proxyPassRetryDelay), maxQuotaResetWait)
	}
	switch {
	case errors.Is(err, guardian.ErrQuotaExceeded):
		if usage := quotaUsageFromError(err); usage != nil && usage.Reset.After(now) {
			return min(usage.Reset.Sub(now)+time.Minute, maxQuotaResetWait)
		}
		if retryAfter := guardian.RetryAfter(err); retryAfter > 0 {
			return min(max(retryAfter, proxyPassRetryDelay), maxQuotaResetWait)
		}
		return terminalRenewalRetryDelay
	case errors.Is(err, fxa.ErrReauthRequired),
		errors.Is(err, guardian.ErrRegionUnavailable),
		errors.Is(err, guardian.ErrNotEntitled):
		return terminalRenewalRetryDelay
	}
	if retryAfter := guardian.RetryAfter(err); retryAfter > proxyPassRetryDelay {
		return min(retryAfter, terminalRenewalRetryDelay)
	}
	return proxyPassRetryDelay
}

// WakeRetryDelay is how long client connections wait after the failures-th
// failed attempt in a row to connect a sleeping proxy to Mozilla before
// they may cause another (a Guardian request each). It is RenewalRetryDelay
// for failures that retrying soon cannot fix (sign in again, a spent quota,
// a refused region, Retry-After); others wait 10 s, doubling with each
// failure up to 2 min.
func WakeRetryDelay(err error, failures int, now time.Time) time.Duration {
	if d := RenewalRetryDelay(err, now); d > proxyPassRetryDelay {
		return d
	}
	d := wakeRetryFirst
	for i := 1; i < failures && d < wakeRetryMax; i++ {
		d *= 2
	}
	return min(d, wakeRetryMax)
}

// LastingWakeFailure reports a failure whose WakeRetryDelay holds for
// connection tests too: retrying it before then cannot succeed.
func LastingWakeFailure(err error, now time.Time) bool {
	return RenewalRetryDelay(err, now) > proxyPassRetryDelay
}

func (c *Controller) RunRenewalLoop() {
	for {
		if c.isClosed() {
			return
		}
		expiry := c.currentExpiry()
		sleep := c.nextRenewalDelay()
		logx.Info("proxy pass renewal scheduled next_expiry=%s delay=%s", expiry.Format(time.RFC3339), sleep)
		if !c.sleepUntil(time.Now().Round(0).Add(sleep)) {
			return
		}
		logx.Info("proxy pass renewal starting")
		err, timedOut, late := c.renewWithDeadline(PassRenewTimeout)
		if timedOut {
			err = fmt.Errorf("proxy pass renewal timed out after %s: %w", PassRenewTimeout, context.DeadlineExceeded)
			// The worker's context is cancelled, so it normally returns at
			// once; its result then counts (a late success is a success).
			// One that does not return holds renewMu, so no new renewal
			// starts until it does. The process keeps running: on Android it
			// carries the phone's VPN, on a desktop the system proxy points
			// at it, and the session serves until its pass expires.
			select {
			case result := <-late:
				err = lateRenewalResult(result, err)
			case <-time.After(proxyPassRenewAbandonGrace):
				c.recordRenewalOutcome(err, time.Now().Add(proxyPassRetryDelay))
				c.writeStatus("renewal_failed")
				logx.Error("proxy pass renewal is stuck after timing out; the next one starts when it returns")
				select {
				case result := <-late:
					logx.Info("the stuck proxy pass renewal returned")
					err = lateRenewalResult(result, err)
				case <-c.done:
					return
				}
			case <-c.done:
				return
			}
		}
		if err == nil {
			continue
		}
		if c.isClosed() {
			return
		}
		now := time.Now()
		retry := RenewalRetryDelay(err, now)
		c.recordRenewalOutcome(err, now.Add(retry))
		logx.Warn("proxy pass renewal failed code=%s retry_in=%s err=%s", renewalFailureCode(err), retry, logx.Err(err))
		if hint := GuardianFailureHint(err); hint != "" {
			logx.Warn("%s", hint)
		}
		c.disableExpiredSession(now)
		c.writeStatus("renewal_failed")
		if !c.sleepOrDone(retry) {
			return
		}
	}
}

// renewWithTimeout runs one renewal whose context is cancelled after
// timeout. It reports timedOut when the deadline passed first; the worker
// then observes the cancellation and unwinds in the background.
func (c *Controller) renewWithTimeout(timeout time.Duration) (error, bool) {
	err, timedOut, _ := c.renewWithDeadline(timeout)
	return err, timedOut
}

// renewWithDeadline is renewWithTimeout that also hands back, when the
// deadline passed first, the channel on which the cancelled worker's own
// result arrives once it unwinds.
func (c *Controller) renewWithDeadline(timeout time.Duration) (error, bool, <-chan error) {
	if timeout <= 0 {
		return c.renew(context.Background()), false, nil
	}

	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	resultCh := make(chan error, 1)
	go func() {
		resultCh <- c.renew(ctx)
	}()

	timer := time.NewTimer(timeout)
	defer timer.Stop()

	select {
	case err := <-resultCh:
		cancel()
		return err, false, nil
	case <-timer.C:
		cancel()
		return nil, true, resultCh
	case <-c.done:
		cancel()
		return nil, false, nil
	}
}

// lateRenewalResult is what a renewal that returned after its deadline
// counts as: nil when it succeeded after all, else the timeout with the
// worker's own error.
func lateRenewalResult(result, timeout error) error {
	if result == nil {
		return nil
	}
	return fmt.Errorf("%w (then: %w)", timeout, result)
}

// wallCheckInterval bounds how long sleepUntil waits between looks at the
// wall clock.
const wallCheckInterval = 15 * time.Second

// sleepUntil waits until the wall clock reaches at (it must carry no
// monotonic reading) or the controller closes. A phone's suspended sleep
// does not advance Go's timers, but a pass expires by the wall clock: one
// long timer would fire after the pass expired, so the wait looks at the
// clock at least every wallCheckInterval and notices a wake-up quickly.
func (c *Controller) sleepUntil(at time.Time) bool {
	for {
		d := time.Until(at)
		if d <= 0 {
			return c.sleepOrDone(0)
		}
		if !c.sleepOrDone(min(d, wallCheckInterval)) {
			return false
		}
	}
}

func (c *Controller) sleepOrDone(d time.Duration) bool {
	if d <= 0 {
		select {
		case <-c.done:
			return false
		default:
			return true
		}
	}

	timer := time.NewTimer(d)
	defer timer.Stop()
	select {
	case <-timer.C:
		return true
	case <-c.done:
		return false
	}
}

func (c *Controller) nextRenewalDelay() time.Duration {
	expiry := c.currentExpiry()
	if expiry.IsZero() {
		return proxyPassRetryDelay
	}
	renewAt := expiry.Add(-proxyPassRenewLead)
	delay := time.Until(renewAt)
	if delay < 0 {
		delay = 0
	}
	c.mu.Lock()
	lastRenewal := c.lastRenewalAt
	c.mu.Unlock()
	if !lastRenewal.IsZero() {
		if floor := minRenewalInterval - time.Since(lastRenewal); floor > delay {
			delay = floor
		}
	}
	return delay
}

func (c *Controller) renew(ctx context.Context) error {
	c.renewMu.Lock()
	defer c.renewMu.Unlock()
	if err := ctx.Err(); err != nil {
		return err
	}
	return c.renewLocked(ctx)
}

// rebuildNeedsPass reports whether the tunnel failure cause says Mozilla
// refused the pass (a CONNECT 401, 403, or 407) or there is no session, so
// only a new pass helps. Anything else (a dead connection, resets,
// timeouts, a run of 502s) is the connection's, and the current pass is
// redialed.
func rebuildNeedsPass(cause error) bool {
	if errors.Is(cause, errProxySessionUnhealthy) {
		return false
	}
	var connectErr *proxyConnectHTTPError
	return errors.As(cause, &connectErr) || errors.Is(cause, ErrNoUsableSession)
}

// rebuildSession replaces failedSession (nil: no session could be taken)
// after a tunnel failure caused by cause.
func (c *Controller) rebuildSession(failedSession *managedSession, cause error) error {
	// Another path may have replaced the session already (Reconnect, a
	// renewal): no need to wait for renewMu, which a renewal holds for a
	// while, to find that out.
	if c.hasUsableSessionOtherThan(failedSession, time.Now()) {
		return nil
	}
	// The phone has no network: nothing to rebuild over. Asking Guardian
	// would only fail, retrying for seconds, and finish once the network is
	// back, in a race with the new network's Reconnect.
	if netstate.ReportedDown() {
		return ErrNoNetwork
	}
	c.renewMu.Lock()
	defer c.renewMu.Unlock()

	// A closed controller fetches no pass and dials nothing.
	if c.isClosed() {
		return ErrNoUsableSession
	}
	if c.hasUsableSessionOtherThan(failedSession, time.Now()) {
		logx.Debug("skipping proxy session rebuild: another usable session is already active")
		return nil
	}
	newPass, err := c.replaceSessionLocked(failedSession, cause)
	if err != nil {
		return err
	}
	if newPass {
		var connectErr *proxyConnectHTTPError
		if errors.As(cause, &connectErr) {
			c.mu.Lock()
			if c.current != nil {
				c.current.afterRefusal = true
			}
			c.mu.Unlock()
		}
	}
	if c.OnSessionRebuilt != nil {
		go c.OnSessionRebuilt()
	}
	return nil
}

// replaceSessionLocked puts a new session in place of failed: a redial
// with the current pass while it has more than the renewal lead left,
// unless cause needs a new pass. It reports whether it fetched a new pass.
func (c *Controller) replaceSessionLocked(failed *managedSession, cause error) (bool, error) {
	if c.refreshSession != nil {
		return rebuildNeedsPass(cause), c.refreshSession()
	}
	now := time.Now()
	if !rebuildNeedsPass(cause) {
		if token, expiresAt, ok := c.redialablePass(failed, now); ok {
			if wait := c.redialBackoff.wait(redialSteps, now); wait > 0 {
				return false, c.redialBackoff.coolingDown(wait)
			}
			// On a stand-in, a rebuild goes back to the location's own
			// server when its avoidance is over; the failure that brought
			// the rebuild was the stand-in's and is not counted against it.
			returned := c.returnToLocation()
			from := c.currentServer()
			err := c.redialLocked(token, expiresAt)
			c.redialBackoff.record(now, cause, err)
			if err == nil {
				logx.Info("upstream proxy session redialed with the current proxy pass")
				// A rebuild counts once against the server: a failed redial
				// counts (dialSession), else the session it replaced, when
				// that broke on the server. Past serverFailoverStrikes the
				// next server of the location replaces the new session too.
				if !returned && failed != nil && c.currentServer().Addr == from.Addr && c.failOver(from, cause) {
					nextErr := c.redialLocked(token, expiresAt)
					c.redialBackoff.record(now, cause, nextErr)
					if nextErr != nil {
						logx.Warn("opening a session on the next server of the location failed; the redialed session serves meanwhile err=%s", logx.Err(nextErr))
					}
				}
			}
			return false, err
		}
		// The pass is about to expire: a new one is due anyway.
	}

	if wait := c.passBackoff.wait(newPassSteps, now); wait > 0 {
		return true, c.passBackoff.coolingDown(wait)
	}
	// The renewal loop's wait after a failure holds here too: a spent
	// quota or an account that must sign in again does not change because
	// a client retries.
	c.mu.Lock()
	retryAt, renewalErr := c.nextAttemptAt, c.lastRenewalErr
	c.mu.Unlock()
	if renewalErr != nil && now.Before(retryAt) {
		return true, fmt.Errorf("%w for %s (the last proxy pass renewal failed): %w", errRebuildCoolingDown, retryAt.Sub(now).Round(time.Second), renewalErr)
	}
	ctx, cancel := context.WithTimeout(context.Background(), PassRenewTimeout)
	defer cancel()
	err := c.renewLocked(ctx)
	c.passBackoff.record(now, cause, err)
	return true, err
}

// redialablePass returns the newest pass (the current session's, else the
// failed one's) when it is valid for more than the renewal lead.
func (c *Controller) redialablePass(failed *managedSession, now time.Time) (string, time.Time, bool) {
	c.mu.Lock()
	defer c.mu.Unlock()
	ms := c.current
	if ms == nil {
		ms = failed
	}
	if ms == nil || ms.rawToken == "" || ms.expiresAt.Sub(now) <= proxyPassRenewLead {
		return "", time.Time{}, false
	}
	return ms.rawToken, ms.expiresAt, true
}

// redialLocked opens a new session with token and makes it current, as
// Reconnect does; renewMu is held, so no renewal changes the pass
// meanwhile. Whether the pass was fetched after a refusal carries over.
func (c *Controller) redialLocked(token string, expiresAt time.Time) error {
	session, err := c.dialSession(token)
	if err != nil {
		return err
	}
	c.mu.Lock()
	afterRefusal := c.current != nil && c.current.afterRefusal
	c.mu.Unlock()
	if !c.swapSession(session, token, expiresAt) {
		return ErrNoUsableSession
	}
	c.mu.Lock()
	if c.current != nil {
		c.current.afterRefusal = afterRefusal
	}
	c.mu.Unlock()
	return nil
}

// dialSession opens a session with token to the current server; renewMu
// is held. A failure that is the server's counts against it (failOver),
// and when that moves the controller to another server of the location,
// the new server is dialed at once.
func (c *Controller) dialSession(token string) (proxySession, error) {
	from := c.currentServer()
	session, err := c.sessionFactory(token)
	if err == nil || !c.failOver(from, err) {
		return session, err
	}
	next := c.currentServer()
	session, err = c.sessionFactory(token)
	if err != nil {
		c.failOver(next, err)
		return nil, err
	}
	logx.Info("upstream proxy session opened on the next server of the location proxy=%s", next.Addr)
	return session, nil
}

func (c *Controller) renewLocked(ctx context.Context) error {
	_, pass, err := c.acquireUsablePass(ctx)
	if err != nil {
		return err
	}
	return c.adoptPass(pass)
}

// acquireUsablePass returns an auth and a proxy pass whose monthly quota is
// not yet exhausted. With an account pool, the pool picks the account and
// fails over between accounts. Without one (single fixed auth, as in tests),
// a Guardian rejection is recovered from by refreshing the OAuth token
// (HTTP 401) or activating the account (HTTP 403).
func (c *Controller) acquireUsablePass(ctx context.Context) (*runtimeAuth, *guardian.ProxyPassInfo, error) {
	if c.accounts != nil {
		auth, pass, err := c.accounts.AcquirePass(ctx, c.guardian)
		if err != nil {
			return nil, nil, err
		}
		c.mu.Lock()
		c.auth = auth
		c.mu.Unlock()
		c.setUsage(pass.Usage)
		return auth, pass, nil
	}
	auth, err := c.ensureOAuthToken(ctx)
	if err != nil {
		return nil, nil, err
	}
	setAuth := func(refreshed *runtimeAuth) {
		c.mu.Lock()
		c.auth = refreshed
		c.mu.Unlock()
	}
	pass, err := fetchProxyPassCtx(ctx, c.guardian, auth.Token.AccessToken)
	if errors.Is(err, guardian.ErrTokenInvalid) {
		auth, pass, err = recoverGuardianRejection(ctx, c.guardian, auth, err, setAuth)
	}
	if err != nil {
		c.setUsage(guardian.UsageFromError(err))
		return nil, nil, err
	}
	c.setUsage(pass.Usage)
	if isQuotaExhausted(pass) {
		return nil, nil, &passQuotaError{usage: pass.Usage}
	}
	return auth, pass, nil
}

// adoptPass applies pass to the current session: when the session supports
// in-place token updates the session is retained, otherwise a fresh session
// pool is built and swapped in while active tunnels drain gracefully.
func (c *Controller) adoptPass(pass *guardian.ProxyPassInfo) error {
	LogPassTimeCorrection(pass)
	c.setUsage(pass.Usage)

	if err := c.updateCurrentSessionToken(pass.RawToken, pass.ExpiresAt()); err == nil {
		c.recordRenewalOutcome(nil, time.Time{})
		c.writeStatus("token_updated")
		logx.Info("proxy pass renewed successfully next_expiry=%s session=retained", pass.ExpiresAt().Format(time.RFC3339))
		return nil
	} else {
		logx.Debug("existing upstream session cannot accept renewed proxy pass; rebuilding err=%s", logx.Err(err))
	}

	session, err := c.dialSession(pass.RawToken)
	if err != nil {
		return err
	}

	c.recordRenewalOutcome(nil, time.Time{})
	if !c.swapSession(session, pass.RawToken, pass.ExpiresAt()) {
		return ErrNoUsableSession
	}
	logx.Info("proxy pass renewed successfully next_expiry=%s", pass.ExpiresAt().Format(time.RFC3339))
	return nil
}

// RunQuotaMonitorLoop reads the quota when heavy traffic brings the active
// account near its switch point (noteTraffic), so the next account takes
// over without waiting for the pass renewal, which reads it otherwise.
func (c *Controller) RunQuotaMonitorLoop() {
	for {
		select {
		case <-c.done:
			return
		case <-c.quotaCheckNow:
			logx.Debug("tunnel traffic reached the usage probe size; checking quota early")
			c.checkQuota()
		}
	}
}

// checkQuota reads the quota with a HEAD request, as Firefox does, so no
// pass is minted while quota remains. Only an exhausted quota or the switch
// threshold with an account pool falls through to pass acquisition, which
// rotates the account; when no other account supplies a pass, the account
// set aside goes on with its current pass.
func (c *Controller) checkQuota() {
	c.renewMu.Lock()
	defer c.renewMu.Unlock()

	c.trafficSinceCheck.Store(0)
	ctx, cancel := context.WithTimeout(context.Background(), PassRenewTimeout)
	defer cancel()

	auth, err := c.ensureOAuthToken(ctx)
	if err != nil {
		logx.Warn("quota check failed: %s", logx.Err(err))
		return
	}
	usageCtx, usageCancel := context.WithTimeout(ctx, APIRequestTimeout)
	usage, err := guardian.FetchProxyUsage(usageCtx, c.guardian, auth.Token.AccessToken)
	usageCancel()
	if errors.Is(err, guardian.ErrTokenInvalid) && !errors.Is(err, guardian.ErrNotEntitled) {
		// Guardian refused the access token: renew now, which refreshes
		// it and signs in again when Mozilla refuses the refresh token,
		// rather than at the next scheduled renewal.
		logx.Warn("Guardian refused the access token in the quota check; renewing now err=%s", logx.Err(err))
		if err := c.renewLocked(ctx); err != nil {
			now := time.Now()
			c.recordRenewalOutcome(err, now.Add(RenewalRetryDelay(err, now)))
			c.writeStatus("renewal_failed")
			logx.Warn("renewal after the quota check failed: %s", logx.Err(err))
		}
		return
	}
	if err != nil {
		logx.Warn("quota check failed: %s", logx.Err(err))
		return
	}
	c.setUsage(usage)
	handOver := usage.Exhausted()
	// setAside is the active account this check takes out of rotation.
	var setAside accounts.Account
	if c.accounts != nil {
		if acc, reached := c.accounts.observeActiveUsage(usage); reached {
			handOver, setAside = true, acc
			logx.Info("active account reached the switch threshold; switching account=%s", logx.Email(acc.Name()))
		}
	}
	c.writeStatus("quota_checked")
	if !handOver {
		return
	}
	if c.accounts == nil {
		logx.Warn("monthly proxy quota exhausted; new tunnels fail once the current proxy pass expires quota_reset=%s", usage.Reset.Format(time.RFC3339))
		return
	}

	_, pass, err := c.acquireUsablePass(ctx)
	if err != nil {
		logx.Warn("quota check failed: %s", logx.Err(err))
		if setAside.ID != "" {
			c.accounts.resumeAfterQuotaCheck(setAside, err)
		}
		return
	}

	c.mu.Lock()
	unchanged := c.current != nil && c.current.rawToken == pass.RawToken
	c.mu.Unlock()
	if unchanged {
		return
	}
	if err := c.adoptPass(pass); err != nil {
		logx.Warn("quota check: could not rebuild proxy sessions: %s", logx.Err(err))
		return
	}
	logx.Info("proxy sessions refreshed after token rotation")
}

func (c *Controller) ensureOAuthToken(ctx context.Context) (*runtimeAuth, error) {
	c.mu.Lock()
	auth := c.auth
	c.mu.Unlock()

	now := time.Now()
	if auth != nil && auth.accessTokenValid(now) {
		return auth, nil
	}
	if auth == nil || auth.Token == nil || auth.Token.RefreshToken == "" {
		return nil, fmt.Errorf("no refresh token available for background renewal")
	}

	logx.Info("refreshing OAuth token")
	refreshed, err := refreshRuntimeAuth(ctx, auth)
	if err != nil {
		return nil, err
	}

	c.mu.Lock()
	c.auth = refreshed
	c.mu.Unlock()
	logx.Info("OAuth token refreshed")
	return refreshed, nil
}

// SwitchAccountNow obtains a pass from the account the account pool now
// prefers (after a manual activation, removal, or disable) and applies it to
// the current upstream session without waiting for the next renewal.
func (c *Controller) SwitchAccountNow() error {
	c.renewMu.Lock()
	defer c.renewMu.Unlock()
	ctx, cancel := context.WithTimeout(context.Background(), PassRenewTimeout)
	defer cancel()
	_, pass, err := c.acquireUsablePass(ctx)
	if err != nil {
		now := time.Now()
		c.recordRenewalOutcome(err, now.Add(RenewalRetryDelay(err, now)))
		c.writeStatus("renewal_failed")
		return err
	}
	return c.adoptPass(pass)
}
