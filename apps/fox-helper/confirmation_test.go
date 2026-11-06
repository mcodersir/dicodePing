package main

import (
	"context"
	"dicodeping/fox/internal/controlplane"
	"dicodeping/fox/internal/fxa"
	"dicodeping/fox/internal/guardian"
	"dicodeping/fox/internal/proxy"
	"io"
	"net/http"
	"strings"
	"testing"
	"testing/synctest"
	"time"
)

func TestSessionWaitsForMozillaConfirmationBeforeIssuingTokens(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		previous := controlplane.Transport()
		t.Cleanup(func() { controlplane.SetTransport(previous) })
		checks, grants := 0, 0
		controlplane.SetTransport(roundTripFunc(func(r *http.Request) (*http.Response, error) {
			status, body := 200, `{}`
			switch r.URL.Path {
			case "/v1/recovery_email/status":
				checks++
				if checks < 2 {
					body = `{"verified":false}`
				} else {
					body = `{"verified":true}`
				}
			case "/v1/oauth/token":
				grants++
				if checks < 2 {
					t.Error("token issued before confirmation")
				}
				body = `{"access_token":"fixture-access","refresh_token":"fixture-refresh","expires_in":3600}`
			default:
				t.Error("unexpected API request")
				status = 500
			}
			return &http.Response{StatusCode: status, Header: make(http.Header), Body: io.NopCloser(strings.NewReader(body)), Request: r}, nil
		}))
		e := &engine{}
		if err := e.session(context.Background(), "fixture@example.test", strings.Repeat("12", 32)); err != nil {
			t.Fatal(err)
		}
		if checks != 2 || grants != 1 || e.snapshot().AccessToken == "" || e.snapshot().SessionToken != "" {
			t.Fatal("confirmation was not committed")
		}
	})
}
func TestManualQuotaRefreshUsesUpstreamHeadThenGet(t *testing.T) {
	previous := controlplane.Transport()
	t.Cleanup(func() { controlplane.SetTransport(previous) })
	methods := []string{}
	controlplane.SetTransport(roundTripFunc(func(r *http.Request) (*http.Response, error) {
		methods = append(methods, r.Method)
		status := 403
		h := make(http.Header)
		if r.Method == http.MethodGet {
			status = 200
			h.Set("X-Quota-Unlimited", "true")
		}
		return &http.Response{StatusCode: status, Header: h, Body: io.NopCloser(strings.NewReader("")), Request: r}, nil
	}))
	auth := proxy.DicodeAuth(&fxa.TokenResponse{AccessToken: "fixture", RefreshToken: "fixture", ExpiresIn: 3600}, time.Now(), func(*fxa.TokenResponse) error { return nil })
	_, usage, err := proxy.DicodeUsage(context.Background(), guardian.DefaultEndpoint, auth, true)
	if err != nil || usage == nil || !usage.Unlimited || strings.Join(methods, ",") != "HEAD,GET" {
		t.Fatalf("manual usage path: %v %v", methods, err)
	}
}
