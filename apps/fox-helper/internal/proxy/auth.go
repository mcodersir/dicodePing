package proxy

import (
	"context"
	"errors"
	"fmt"
	"time"

	"dicodeping/fox/internal/fxa"
	"dicodeping/fox/internal/logx"
)

const oauthRefreshLead = 2 * time.Minute

func refreshRuntimeAuth(ctx context.Context, auth *runtimeAuth) (*runtimeAuth, error) {
	if auth == nil || auth.Token == nil || auth.Token.RefreshToken == "" {
		return nil, fmt.Errorf("no refresh token available")
	}
	token, err := fxa.RefreshToken(fxa.WithRequestTimeout(ctx, APIRequestTimeout), auth.Token.RefreshToken)
	if err != nil {
		return nil, err
	}
	refreshed := &runtimeAuth{Token: token, ObtainedAt: time.Now(), persist: auth.persist, accountID: auth.accountID}
	if err := refreshed.save(); err != nil {
		logx.Warn("saving refreshed tokens failed: %v", err)
	}
	return refreshed, nil
}

// FreshRuntimeAuth returns auth when its access token is still valid and a
// refreshed auth otherwise.
func FreshRuntimeAuth(ctx context.Context, auth *runtimeAuth) (*runtimeAuth, error) {
	if auth.accessTokenValid(time.Now()) {
		return auth, nil
	}
	if auth == nil || auth.Token == nil || auth.Token.RefreshToken == "" {
		return nil, fmt.Errorf("%w: no refresh token stored", fxa.ErrReauthRequired)
	}
	refreshed, err := refreshRuntimeAuth(ctx, auth)
	if err != nil && ctx.Err() == nil && !errors.Is(err, fxa.ErrReauthRequired) && auth.Token.AccessToken != "" {
		// A proactive refresh failure must not discard a grant that Mozilla
		// has not expired. Never change its expiry or mask revoked tokens.
		expiry := auth.ObtainedAt.Add(time.Duration(auth.Token.ExpiresIn) * time.Second)
		if time.Now().Before(expiry) {
			logx.Warn("proactive OAuth refresh unavailable; retaining unexpired access grant")
			return auth, nil
		}
	}
	return refreshed, err
}

type runtimeAuth struct {
	Token      *fxa.TokenResponse
	ObtainedAt time.Time

	// persist stores refreshed credentials in the account store.
	persist func(*runtimeAuth) error
	// accountID names the stored account in multi-account mode.
	accountID string
}

// save persists the credentials where they were loaded from; auths
// without a store (tests) are kept in memory only.
func (a *runtimeAuth) save() error {
	if a.persist != nil {
		return a.persist(a)
	}
	return nil
}

func (a *runtimeAuth) accessTokenValid(now time.Time) bool {
	if a == nil || a.Token == nil || a.Token.AccessToken == "" {
		return false
	}
	expiry := a.ObtainedAt.Add(time.Duration(a.Token.ExpiresIn) * time.Second)
	return now.Before(expiry.Add(-oauthRefreshLead))
}
