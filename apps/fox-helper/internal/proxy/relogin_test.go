package proxy

import (
	"context"
	"errors"
	"net/http"
	"sync/atomic"
	"testing"

	"dicodeping/fox/internal/accounts"
)

func TestGuardianRejectsRefreshedTokenWithoutSigningIn(t *testing.T) {
	pool, accs := newTestAccountPool(t, "a")
	id := accs["a"].ID
	if err := pool.store.SetPassword(id, "fixture-password"); err != nil {
		t.Fatal(err)
	}
	var logins, refreshes atomic.Int32
	setCoreControlPlane(t, func(r *http.Request) (*http.Response, error) {
		switch r.URL.Host {
		case "api.accounts.firefox.com":
			switch r.URL.Path {
			case "/v1/account/login":
				logins.Add(1)
			case "/v1/oauth/token":
				refreshes.Add(1)
				return coreResponse(r, http.StatusOK, `{"access_token":"refreshed-access","refresh_token":"refresh-a","expires_in":3600}`, nil), nil
			}
		case "guardian.invalid":
			return coreResponse(r, http.StatusUnauthorized, `{"error":"invalid token"}`, nil), nil
		}
		return nil, errors.New("unexpected request")
	})
	if _, _, err := pool.AcquirePass(context.Background(), "https://guardian.invalid"); err == nil {
		t.Fatal("expected no usable pass")
	}
	if logins.Load() != 0 || refreshes.Load() != 1 {
		t.Fatalf("got %d password sign-ins and %d OAuth refreshes", logins.Load(), refreshes.Load())
	}
	if a := accountStatus(t, pool, id); a.Status != accounts.StatusReauthRequired || a.ReasonCode != accounts.ReasonSignInRequired {
		t.Fatalf("status %s reason %q", a.Status, a.ReasonCode)
	}
}
