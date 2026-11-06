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

const invalidTokenBody = `{"code":401,"errno":110,"message":"Invalid authentication token in request signature"}`

// revokedFixture answers FxA and Guardian for accounts whose refresh token
// Mozilla revoked: the device endpoint and the refresh refuse the stored
// tokens, a sign-in issues "new-access"/"new-refresh", and Guardian
// accepts only "new-access" unless acceptOld.
func revokedFixture(t *testing.T, verified bool, acceptOld bool) (logins, devices *atomic.Int32) {
	t.Helper()
	logins, devices = new(atomic.Int32), new(atomic.Int32)
	setCoreControlPlane(t, func(r *http.Request) (*http.Response, error) {
		bearer := strings.TrimPrefix(r.Header.Get("Authorization"), "Bearer ")
		if r.URL.Host == "api.accounts.firefox.com" {
			var body map[string]any
			if r.Body != nil {
				_ = json.NewDecoder(r.Body).Decode(&body)
			}
			switch {
			case r.URL.Path == "/v1/account/device" && bearer == "new-refresh":
				devices.Add(1)
				return coreResponse(r, http.StatusOK, `{"id":"dev-new","name":"Firefox's built-in VPN"}`, nil), nil
			case r.URL.Path == "/v1/account/device":
				return coreResponse(r, http.StatusUnauthorized, invalidTokenBody, nil), nil
			case r.URL.Path == "/v1/account/login":
				logins.Add(1)
				v := "true"
				if !verified {
					v = `false,"verificationMethod":"email-otp"`
				}
				return coreResponse(r, http.StatusOK, `{"uid":"u1","sessionToken":"`+strings.Repeat("ab", 32)+`","verified":`+v+`}`, nil), nil
			case r.URL.Path == "/v1/session/destroy":
				return coreResponse(r, http.StatusOK, `{}`, nil), nil
			case r.URL.Path == "/v1/oauth/token" && body["grant_type"] == "refresh_token":
				return coreResponse(r, http.StatusUnauthorized, invalidTokenBody, nil), nil
			case r.URL.Path == "/v1/oauth/token":
				return coreResponse(r, http.StatusOK, `{"access_token":"new-access","refresh_token":"new-refresh","expires_in":3600,"token_type":"bearer"}`, nil), nil
			}
			return nil, errors.New("unexpected FxA request " + r.URL.Path)
		}
		if bearer == "new-access" || (acceptOld && strings.HasPrefix(bearer, "access-")) {
			if r.Method == http.MethodHead {
				return coreResponse(r, http.StatusOK, "", quotaHeader(1)), nil
			}
			return coreResponse(r, http.StatusOK, `{"token":"`+accountJWT("a")+`"}`, quotaHeader(1)), nil
		}
		return coreResponse(r, http.StatusUnauthorized, `{"error":"invalid token"}`, nil), nil
	})
	DeviceRegistration.Store(true)
	t.Cleanup(func() { DeviceRegistration.Store(false) })
	return logins, devices
}

// Device registration is where a revoked refresh token shows first (in the
// user's test, at every start for 24 hours while Guardian kept accepting
// the access token): the account signs in again at once.
func TestRevokedRefreshTokenSignsInAgainAtOnce(t *testing.T) {
	pool, accs := newTestAccountPool(t, "a")
	id := accs["a"].ID
	if err := pool.store.SetPassword(id, "secret"); err != nil {
		t.Fatal(err)
	}
	logins, devices := revokedFixture(t, true, true)

	pool.EnsureDevice(context.Background(), id)

	if logins.Load() != 1 {
		t.Fatalf("expected one automatic sign-in, got %d", logins.Load())
	}
	if creds, _ := pool.store.Credentials(id); creds.RefreshToken != "new-refresh" {
		t.Fatal("the new tokens must be stored")
	}
	waitForCondition(t, 5*time.Second, func() bool {
		acc, err := pool.store.Get(id)
		return err == nil && acc.DeviceID == "dev-new" && devices.Load() == 1
	})
	if a := accountStatus(t, pool, id); a.Status != accounts.StatusReady {
		t.Fatalf("status %s %q", a.Status, a.Reason)
	}
}

// When the sign-in needs a confirmation code, the account is marked for
// "Sign in again" so the user hears of it now, unless it is the only
// account the proxy can use: its access token still works until it
// expires.
func TestRevokedRefreshTokenNeedingCode(t *testing.T) {
	t.Run("another account takes over", func(t *testing.T) {
		pool, accs := newTestAccountPool(t, "a", "b")
		id := accs["a"].ID
		if err := pool.mgr.Activate(id); err != nil {
			t.Fatal(err)
		}
		if err := pool.store.SetPassword(id, "secret"); err != nil {
			t.Fatal(err)
		}
		revokedFixture(t, false, true)
		pool.EnsureDevice(context.Background(), id)
		if a := accountStatus(t, pool, id); a.Status != accounts.StatusReauthRequired {
			t.Fatalf("status %s %q", a.Status, a.Reason)
		}
	})
	t.Run("the only account keeps working", func(t *testing.T) {
		pool, accs := newTestAccountPool(t, "a")
		id := accs["a"].ID
		if err := pool.mgr.Activate(id); err != nil {
			t.Fatal(err)
		}
		if err := pool.store.SetPassword(id, "secret"); err != nil {
			t.Fatal(err)
		}
		revokedFixture(t, false, true)
		pool.EnsureDevice(context.Background(), id)
		if a := accountStatus(t, pool, id); a.Status != accounts.StatusReady {
			t.Fatalf("status %s %q", a.Status, a.Reason)
		}
	})
}

// A 401 in the quota check renews at once (refresh, then a new sign-in)
// instead of waiting for the next scheduled renewal.
func TestQuotaCheckRefusedTokenRenewsNow(t *testing.T) {
	pool, accs := newTestAccountPool(t, "a")
	id := accs["a"].ID
	if err := pool.mgr.Activate(id); err != nil {
		t.Fatal(err)
	}
	if err := pool.store.SetPassword(id, "secret"); err != nil {
		t.Fatal(err)
	}
	authA, err := pool.AuthFor(accs["a"])
	if err != nil {
		t.Fatal(err)
	}
	logins, devices := revokedFixture(t, true, false)

	session := &fakeProxySession{token: "pass-a"}
	controller := &Controller{
		guardian:      "https://guardian.invalid",
		accounts:      pool,
		auth:          authA,
		quotaCheckNow: make(chan struct{}, 1),
		done:          make(chan struct{}),
		current:       &managedSession{session: session, rawToken: "pass-a", expiresAt: time.Now().Add(10 * time.Minute), accepting: true},
		sessionFactory: func(string) (proxySession, error) {
			return nil, errors.New("a renewal must not rebuild the upstream session")
		},
	}
	controller.checkQuota()

	if logins.Load() != 1 {
		t.Fatalf("expected one automatic sign-in, got %d", logins.Load())
	}
	if session.currentToken() == "pass-a" {
		t.Fatal("expected the session to carry the new pass")
	}
	// The sign-in registers the new token's device in the background.
	waitForCondition(t, 5*time.Second, func() bool {
		acc, err := pool.store.Get(id)
		return err == nil && acc.DeviceID == "dev-new" && devices.Load() == 1
	})
}
