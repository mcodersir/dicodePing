package proxy

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"dicodeping/fox/internal/fxa"
	"dicodeping/fox/internal/guardian"
)

func TestIsQuotaExhausted(t *testing.T) {
	t.Parallel()

	cases := []struct {
		name string
		pass *guardian.ProxyPassInfo
		want bool
	}{
		{"nil pass", nil, false},
		{"no quota headers", &guardian.ProxyPassInfo{}, false},
		{"zero remaining", &guardian.ProxyPassInfo{QuotaLeft: "0"}, true},
		{"quota remaining", &guardian.ProxyPassInfo{QuotaLeft: "1073741824"}, false},
		{"unparsable value", &guardian.ProxyPassInfo{QuotaLeft: "n/a"}, false},
	}
	for _, tc := range cases {
		if got := isQuotaExhausted(tc.pass); got != tc.want {
			t.Errorf("%s: expected %v, got %v", tc.name, tc.want, got)
		}
	}
}

func TestFetchProxyPassRetriesTransientGuardianFailure(t *testing.T) {
	var calls atomic.Int32
	pass := coreFixtureJWT(10 * time.Minute)
	setCoreControlPlane(t, func(r *http.Request) (*http.Response, error) {
		if !strings.HasSuffix(r.URL.Path, "/api/v1/fpn/token") {
			return nil, fmt.Errorf("unexpected request")
		}
		if calls.Add(1) < 3 {
			return coreResponse(r, http.StatusServiceUnavailable, "busy", nil), nil
		}
		return coreResponse(r, http.StatusOK, `{"token":"`+pass+`"}`, nil), nil
	})

	got, err := fetchProxyPassCtx(context.Background(), "https://guardian.invalid", "access")
	if err != nil || got.RawToken != pass || calls.Load() != 3 {
		t.Fatalf("expected success on the third attempt, got calls=%d err=%v", calls.Load(), err)
	}
}

func TestFetchProxyPassDoesNotRetryRegionRefusalBeyondTheDoubledPath(t *testing.T) {
	var calls atomic.Int32
	var paths []string
	setCoreControlPlane(t, func(r *http.Request) (*http.Response, error) {
		calls.Add(1)
		paths = append(paths, r.URL.Path)
		return coreResponse(r, http.StatusUnavailableForLegalReasons, "region", nil), nil
	})

	_, err := fetchProxyPassCtx(context.Background(), "https://guardian.invalid", "access")
	if !errors.Is(err, guardian.ErrRegionUnavailable) || calls.Load() != 2 {
		t.Fatalf("expected two region refusals (original and doubled path), got calls=%d err=%v", calls.Load(), err)
	}
	want := []string{"/api/v1/fpn/token", "//api/v1/fpn/token"}
	if len(paths) != 2 || paths[0] != want[0] || paths[1] != want[1] {
		t.Fatalf("paths = %v, want %v", paths, want)
	}
	if GuardianFailureHint(err) == "" {
		t.Fatal("expected an operator hint for HTTP 451")
	}
}

func TestAcquireUsablePassActivatesOnNotEntitledWithoutRefresh(t *testing.T) {
	var activated atomic.Bool
	pass := coreFixtureJWT(10 * time.Minute)
	setCoreControlPlane(t, func(r *http.Request) (*http.Response, error) {
		switch {
		case strings.HasSuffix(r.URL.Path, "/api/v1/fpn/activate") && r.Method == http.MethodPost:
			activated.Store(true)
			return coreResponse(r, http.StatusOK, `{"subscribed":false,"uid":1,"maxBytes":"0"}`, nil), nil
		case strings.HasSuffix(r.URL.Path, "/api/v1/fpn/token") && !activated.Load():
			return coreResponse(r, http.StatusForbidden, "not entitled", nil), nil
		case strings.HasSuffix(r.URL.Path, "/api/v1/fpn/token"):
			return coreResponse(r, http.StatusOK, `{"token":"`+pass+`"}`, nil), nil
		}
		return nil, fmt.Errorf("unexpected request (an OAuth refresh is not expected) %s", r.URL)
	})

	auth := &runtimeAuth{Token: &fxa.TokenResponse{AccessToken: "access", RefreshToken: "refresh", ExpiresIn: 3600}, ObtainedAt: time.Now()}
	controller := &Controller{guardian: "https://guardian.invalid", auth: auth}
	gotAuth, got, err := controller.acquireUsablePass(context.Background())
	if err != nil || got.RawToken != pass || gotAuth != auth || !activated.Load() {
		t.Fatalf("expected activation then a pass with the same auth, got err=%v activated=%v", err, activated.Load())
	}
}

func TestAcquireUsablePassRefusesExhaustedQuota(t *testing.T) {
	pass := coreFixtureJWT(10 * time.Minute)
	setCoreControlPlane(t, func(r *http.Request) (*http.Response, error) {
		header := make(http.Header)
		header.Set("X-Quota-Limit", "100")
		header.Set("X-Quota-Remaining", "0")
		header.Set("X-Quota-Reset", "2026-11-01T00:00:00Z")
		return coreResponse(r, http.StatusOK, `{"token":"`+pass+`"}`, header), nil
	})

	auth := &runtimeAuth{Token: &fxa.TokenResponse{AccessToken: "access", ExpiresIn: 3600}, ObtainedAt: time.Now()}
	controller := &Controller{guardian: "https://guardian.invalid", auth: auth}
	_, _, err := controller.acquireUsablePass(context.Background())
	if !errors.Is(err, guardian.ErrQuotaExceeded) || !strings.Contains(err.Error(), "2026-11-01") {
		t.Fatalf("expected a quota error naming the reset time, got %v", err)
	}
}
