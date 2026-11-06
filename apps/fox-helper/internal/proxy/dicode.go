package proxy

// DicodeAuth attaches the host application's encrypted vault to Arman's
// refresh/recovery controller. No credentials are written to disk by this adapter.
import (
	"context"
	"dicodeping/fox/internal/fxa"
	"dicodeping/fox/internal/guardian"
	"errors"
	"time"
)

func DicodeAuth(token *fxa.TokenResponse, obtained time.Time, save func(*fxa.TokenResponse) error) *runtimeAuth {
	return &runtimeAuth{Token: token, ObtainedAt: obtained, persist: func(a *runtimeAuth) error { return save(a.Token) }}
}

func DicodePass(ctx context.Context, endpoint string, auth *runtimeAuth) (*runtimeAuth, *guardian.ProxyPassInfo, error) {
	fresh, err := FreshRuntimeAuth(ctx, auth)
	if err != nil {
		return auth, nil, err
	}
	pass, err := fetchProxyPassCtx(ctx, endpoint, fresh.Token.AccessToken)
	if err != nil && (errors.Is(err, guardian.ErrTokenInvalid)) {
		fresh, pass, err = recoverGuardianRejection(ctx, endpoint, fresh, err, nil)
	}
	if err == nil && isQuotaExhausted(pass) {
		return fresh, pass, &passQuotaError{usage: pass.Usage}
	}
	return fresh, pass, err
}
