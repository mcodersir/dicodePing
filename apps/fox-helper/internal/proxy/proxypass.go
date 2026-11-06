package proxy

import (
	"context"
	"errors"
	"fmt"
	"strconv"
	"time"

	"dicodeping/fox/internal/fxa"
	"dicodeping/fox/internal/guardian"
	"dicodeping/fox/internal/logx"
)

const (
	// terminalRenewalRetryDelay spaces renewal attempts after a failure that
	// retrying cannot fix soon (sign-in required, region refused, no
	// entitlement, spent quota without a known reset time).
	terminalRenewalRetryDelay = 15 * time.Minute

	// maxQuotaResetWait caps how long renewal waits for a known quota reset.
	maxQuotaResetWait = 6 * time.Hour
)

var (
	// GuardianRetryInitialDelay and guardianRetryBudget bound the retries
	// of a transient ProxyPass fetch failure, matching Firefox (500 ms
	// doubling backoff inside a 30 s budget). Tests may shorten them.
	GuardianRetryInitialDelay = 500 * time.Millisecond
	guardianRetryBudget       = 30 * time.Second
)

// fetchProxyPassCtx fetches a ProxyPass, retrying transient failures
// (transport errors and HTTP 5xx) with exponential backoff inside
// guardianRetryBudget, like Firefox's pass rotation. A Retry-After that does
// not fit the remaining budget ends the retries. Every other answer is
// returned at once.
func fetchProxyPassCtx(ctx context.Context, endpoint, accessToken string) (*guardian.ProxyPassInfo, error) {
	budgetCtx, cancelBudget := context.WithTimeout(ctx, guardianRetryBudget)
	defer cancelBudget()
	delay := GuardianRetryInitialDelay
	for attempt := 1; ; attempt++ {
		attemptCtx, cancel := context.WithTimeout(budgetCtx, APIRequestTimeout)
		pass, err := guardian.FetchProxyPass(attemptCtx, endpoint, accessToken)
		cancel()
		if err == nil || !guardian.IsTransient(err) || ctx.Err() != nil {
			return pass, err
		}
		wait := delay
		if retryAfter := guardian.RetryAfter(err); retryAfter > wait {
			wait = retryAfter
		}
		if deadline, ok := budgetCtx.Deadline(); ok && time.Until(deadline) < wait {
			return nil, err
		}
		logx.Warn("guardian request failed; retrying attempt=%d delay=%s err=%s", attempt, wait, logx.Err(err))
		timer := time.NewTimer(wait)
		select {
		case <-timer.C:
		case <-budgetCtx.Done():
			timer.Stop()
			return nil, err
		}
		delay *= 2
	}
}

// GuardianFailureHint explains Guardian failures that retrying cannot fix.
func GuardianFailureHint(err error) string {
	switch {
	case errors.Is(err, guardian.ErrRegionUnavailable):
		return "Guardian refuses requests from this region (HTTP 451); set network.api_relay to your own relay in a supported region (scripts/relay)"
	case errors.Is(err, fxa.ErrReauthRequired):
		return "the saved Firefox Account credential was rejected; sign the account in again from the dashboard"
	case errors.Is(err, guardian.ErrQuotaExceeded):
		return "the account's monthly proxy quota is exhausted; wait for the quota reset"
	case errors.Is(err, guardian.ErrNotEntitled):
		return "the account is not entitled to the Firefox VPN proxy and activation did not grant access"
	}
	return ""
}

// isQuotaExhausted reports whether the proxy pass quota headers indicate
// that no monthly traffic is left. An unlimited account is never exhausted.
func isQuotaExhausted(pass *guardian.ProxyPassInfo) bool {
	if pass == nil {
		return false
	}
	if pass.Usage != nil {
		return pass.Usage.Exhausted()
	}
	if pass.QuotaLeft == "" {
		return false
	}
	left, err := strconv.ParseInt(pass.QuotaLeft, 10, 64)
	if err != nil {
		return false
	}
	return left <= 0
}

// recoverGuardianRejection applies Guardian's meaning of a rejected pass
// request, as Firefox's GuardianClient does: HTTP 401 means the OAuth access
// token was refused, so it is refreshed; HTTP 403 means the account lacks
// the proxy entitlement, so it is activated. It returns the auth now in use
// and the outcome of the last pass request. onRefresh, when set, receives a
// refreshed auth as soon as it exists.
func recoverGuardianRejection(ctx context.Context, endpoint string, auth *runtimeAuth, fetchErr error, onRefresh func(*runtimeAuth)) (*runtimeAuth, *guardian.ProxyPassInfo, error) {
	var pass *guardian.ProxyPassInfo
	if !errors.Is(fetchErr, guardian.ErrNotEntitled) {
		logx.Info("OAuth access was rejected by Guardian; refreshing token")
		refreshed, refreshErr := refreshRuntimeAuth(ctx, auth)
		if refreshErr != nil {
			logx.Warn("refreshing OAuth token after Guardian rejection failed: %s", logx.Err(refreshErr))
			if errors.Is(refreshErr, fxa.ErrReauthRequired) {
				return auth, nil, refreshErr
			}
			return auth, nil, fetchErr
		}
		auth = refreshed
		if onRefresh != nil {
			onRefresh(refreshed)
		}
		pass, fetchErr = fetchProxyPassCtx(ctx, endpoint, auth.Token.AccessToken)
		if !errors.Is(fetchErr, guardian.ErrNotEntitled) {
			return auth, pass, fetchErr
		}
	}

	logx.Info("Guardian reports no proxy entitlement for this account; activating")
	activateCtx, cancel := context.WithTimeout(ctx, APIRequestTimeout)
	_, activateErr := guardian.Activate(activateCtx, endpoint, auth.Token.AccessToken)
	cancel()
	if activateErr != nil {
		logx.Warn("activating Guardian account failed: %s", logx.Err(activateErr))
		if errors.Is(activateErr, guardian.ErrRegionUnavailable) {
			return auth, nil, activateErr
		}
		return auth, nil, fetchErr
	}
	logx.Info("Guardian account activated")
	pass, fetchErr = fetchProxyPassCtx(ctx, endpoint, auth.Token.AccessToken)
	return auth, pass, fetchErr
}

// passQuotaError reports a pass whose quota headers show no traffic left.
type passQuotaError struct {
	usage *guardian.ProxyUsage
}

func (e *passQuotaError) Error() string {
	if e.usage != nil && !e.usage.Reset.IsZero() {
		return fmt.Sprintf("%s: no quota remaining until %s", guardian.ErrQuotaExceeded, e.usage.Reset.Format(time.RFC3339))
	}
	return fmt.Sprintf("%s: no quota remaining", guardian.ErrQuotaExceeded)
}

func (e *passQuotaError) Unwrap() error { return guardian.ErrQuotaExceeded }

// quotaUsageFromError returns the quota state carried by a Guardian or
// exhausted-pass error, or nil.
func quotaUsageFromError(err error) *guardian.ProxyUsage {
	var quotaErr *passQuotaError
	if errors.As(err, &quotaErr) {
		return quotaErr.usage
	}
	return guardian.UsageFromError(err)
}

func LogPassTimeCorrection(pass *guardian.ProxyPassInfo) {
	if pass == nil || pass.ClaimTimeCorrection() == 0 {
		return
	}
	logx.Warn("proxy pass JWT claim time correction applied offset=%s expires_at=%s", pass.ClaimTimeCorrection(), pass.ExpiresAt().Format(time.RFC3339))
}
