package proxy

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"dicodeping/fox/internal/accounts"
)

// All credentials in this file are local fixtures; the control plane
// transport rejects every request it does not recognise.

// reloginFixture answers FxA and Guardian for one account "a": Guardian
// accepts only the access token of a new sign-in ("new-access"); a refresh
// returns another token Guardian refuses too. loginErr, when set, answers
// the sign-in instead.
func reloginFixture(t *testing.T, logins *atomic.Int32, loginErr func(*http.Request) (*http.Response, error)) {
	t.Helper()
	setCoreControlPlane(t, func(r *http.Request) (*http.Response, error) {
		if r.URL.Host == "api.accounts.firefox.com" {
			var body map[string]any
			if r.Body != nil {
				_ = json.NewDecoder(r.Body).Decode(&body)
			}
			switch {
			case r.URL.Path == "/v1/account/login":
				logins.Add(1)
				if loginErr != nil {
					return loginErr(r)
				}
				return coreResponse(r, http.StatusOK, `{"uid":"u1","sessionToken":"`+strings.Repeat("ab", 32)+`","verified":true}`, nil), nil
			case r.URL.Path == "/v1/session/destroy":
				return coreResponse(r, http.StatusOK, `{}`, nil), nil
			case r.URL.Path == "/v1/oauth/token" && body["grant_type"] == "refresh_token":
				return coreResponse(r, http.StatusOK, `{"access_token":"refreshed-access","refresh_token":"refresh-a","expires_in":3600,"token_type":"bearer"}`, nil), nil
			case r.URL.Path == "/v1/oauth/token":
				return coreResponse(r, http.StatusOK, `{"access_token":"new-access","refresh_token":"new-refresh","expires_in":3600,"token_type":"bearer"}`, nil), nil
			}
			return nil, errors.New("unexpected FxA request " + r.URL.Path)
		}
		if r.Header.Get("Authorization") == "Bearer new-access" {
			return coreResponse(r, http.StatusOK, `{"token":"`+accountJWT("a")+`"}`, quotaHeader(1)), nil
		}
		return coreResponse(r, http.StatusUnauthorized, `{"error":"invalid token"}`, nil), nil
	})
}

// Guardian refuses the account's tokens and a refresh does not help: the
// account signs in again with its stored password and continues.
func TestReloginWhenGuardianKeepsRefusingTokens(t *testing.T) {
	pool, accs := newTestAccountPool(t, "a")
	id := accs["a"].ID
	if err := pool.store.SetPassword(id, "secret"); err != nil {
		t.Fatal(err)
	}
	var logins atomic.Int32
	reloginFixture(t, &logins, nil)

	auth, pass, err := pool.AcquirePass(context.Background(), "https://guardian.invalid")
	if err != nil || pass == nil {
		t.Fatalf("expected a pass after the automatic sign-in: %v", err)
	}
	if auth.Token.AccessToken != "new-access" || logins.Load() != 1 {
		t.Fatalf("token %q after %d sign-ins", auth.Token.AccessToken, logins.Load())
	}
	if creds, _ := pool.store.Credentials(id); creds.RefreshToken != "new-refresh" {
		t.Fatalf("new tokens not stored: %+v", creds)
	}
	if a := accountStatus(t, pool, id); a.Status != accounts.StatusReady {
		t.Fatalf("status %s %q", a.Status, a.Reason)
	}
}

// A sign-in that cannot reach Mozilla does not ask the user to sign in: the
// account sits out briefly and the sign-in is tried again.
func TestReloginNetworkFailureIsRetried(t *testing.T) {
	pool, accs := newTestAccountPool(t, "a")
	id := accs["a"].ID
	if err := pool.store.SetPassword(id, "secret"); err != nil {
		t.Fatal(err)
	}
	var logins atomic.Int32
	reloginFixture(t, &logins, func(*http.Request) (*http.Response, error) {
		return nil, errors.New("connection reset")
	})

	if _, _, err := pool.AcquirePass(context.Background(), "https://guardian.invalid"); err == nil {
		t.Fatal("expected no pass while Mozilla is unreachable")
	}
	a := accountStatus(t, pool, id)
	if a.Status != accounts.StatusUnavailable || a.RetryAt.IsZero() || a.RetryAt.After(time.Now().Add(reloginNetworkRetry)) || !strings.Contains(a.Reason, "trying again") {
		t.Fatalf("status %s until %v: %q", a.Status, a.RetryAt, a.Reason)
	}
	// The next attempt is not held back by the 30-minute spacing.
	if _, err := pool.Relogin(context.Background(), a, errors.New("cause")); err == nil || logins.Load() < 2 {
		t.Fatalf("the sign-in must be tried again: %v logins=%d", err, logins.Load())
	}
}

// Mozilla refusing the stored password needs the user.
func TestReloginWrongPasswordNeedsSignIn(t *testing.T) {
	pool, accs := newTestAccountPool(t, "a")
	id := accs["a"].ID
	if err := pool.store.SetPassword(id, "old"); err != nil {
		t.Fatal(err)
	}
	var logins atomic.Int32
	reloginFixture(t, &logins, func(r *http.Request) (*http.Response, error) {
		return coreResponse(r, http.StatusBadRequest, `{"code":400,"errno":103,"message":"Incorrect password"}`, nil), nil
	})

	if _, _, err := pool.AcquirePass(context.Background(), "https://guardian.invalid"); err == nil {
		t.Fatal("expected no pass")
	}
	if a := accountStatus(t, pool, id); a.Status != accounts.StatusReauthRequired || !strings.Contains(a.Reason, "Incorrect password") {
		t.Fatalf("status %s %q", a.Status, a.Reason)
	}
}
