package guardian

import (
	"encoding/base64"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"strings"
	"testing"
	"time"

	"dicodeping/fox/internal/controlplane"
)

func TestFetchProxyPassSendsNoCacheAndAnchorsExpiry(t *testing.T) {
	previous := controlplane.Transport()
	t.Cleanup(func() { controlplane.SetTransport(previous) })

	// Claims eight hours in the past, as if Guardian's clock were skewed.
	skewed := time.Now().Add(-8 * time.Hour)
	token := testJWT(t, map[string]any{"sub": "s", "aud": "https://vpn.mozilla.org", "iss": "https://vpn.mozilla.org", "iat": skewed.Unix(), "nbf": skewed.Unix(), "exp": skewed.Add(10 * time.Minute).Unix()})
	controlplane.SetTransport(roundTripFunc(func(r *http.Request) (*http.Response, error) {
		if r.Header.Get("Cache-Control") != "max-age=0" || r.Header.Get("Pragma") != "" || r.Header.Get("Authorization") != "Bearer access" {
			t.Errorf("unexpected Guardian request headers: %v", r.Header)
		}
		header := make(http.Header)
		header.Set("X-Quota-Unlimited", "true")
		return &http.Response{StatusCode: http.StatusOK, Header: header, Body: io.NopCloser(strings.NewReader(`{"token":"` + token + `"}`)), Request: r}, nil
	}))

	before := time.Now()
	pass, err := FetchProxyPass(t.Context(), "https://guardian.invalid", "access")
	if err != nil {
		t.Fatal(err)
	}
	if pass.Usage == nil || !pass.Usage.Unlimited {
		t.Fatalf("expected unlimited usage, got %#v", pass.Usage)
	}
	if remaining := time.Until(pass.ExpiresAt()); remaining < 9*time.Minute || pass.ExpiresAt().After(before.Add(10*time.Minute+2*time.Second)) {
		t.Fatalf("expected anchored ten-minute lifetime, got expiry %s", pass.ExpiresAt())
	}
}

func TestFetchProxyPassRetriesOnADoubledPathWhenTheRegionIsRefused(t *testing.T) {
	previous := controlplane.Transport()
	t.Cleanup(func() { controlplane.SetTransport(previous); SetRegionRecovery(nil) })

	now := time.Now()
	token := testJWT(t, map[string]any{"sub": "s", "aud": "https://vpn.mozilla.org", "iss": "https://vpn.mozilla.org", "iat": now.Unix(), "nbf": now.Unix(), "exp": now.Add(10 * time.Minute).Unix()})
	var paths []string
	controlplane.SetTransport(roundTripFunc(func(r *http.Request) (*http.Response, error) {
		paths = append(paths, r.URL.Path)
		if r.URL.Path != "//api/v1/fpn/token" {
			return &http.Response{StatusCode: http.StatusUnavailableForLegalReasons, Header: make(http.Header), Body: io.NopCloser(strings.NewReader(`{"error":"unavailable_in_region"}`)), Request: r}, nil
		}
		header := make(http.Header)
		header.Set("X-Quota-Unlimited", "true")
		return &http.Response{StatusCode: http.StatusOK, Header: header, Body: io.NopCloser(strings.NewReader(`{"token":"` + token + `"}`)), Request: r}, nil
	}))

	pass, err := FetchProxyPass(t.Context(), "https://guardian.invalid", "access")
	if err != nil {
		t.Fatal(err)
	}
	if pass.RawToken != token {
		t.Fatalf("unexpected token %q", pass.RawToken)
	}
	want := []string{"/api/v1/fpn/token", "//api/v1/fpn/token"}
	if strings.Join(paths, ",") != strings.Join(want, ",") {
		t.Fatalf("paths = %v, want %v", paths, want)
	}
}

func TestFetchProxyPassDoesNotRetryOtherStatuses(t *testing.T) {
	previous := controlplane.Transport()
	t.Cleanup(func() { controlplane.SetTransport(previous); SetRegionRecovery(nil) })

	var paths []string
	controlplane.SetTransport(roundTripFunc(func(r *http.Request) (*http.Response, error) {
		paths = append(paths, r.URL.Path)
		return &http.Response{StatusCode: http.StatusUnauthorized, Header: make(http.Header), Body: io.NopCloser(strings.NewReader(`{"error":"Unauthorized"}`)), Request: r}, nil
	}))

	if _, err := FetchProxyPass(t.Context(), "https://guardian.invalid", "access"); !errors.Is(err, ErrTokenInvalid) {
		t.Fatalf("err = %v, want ErrTokenInvalid", err)
	}
	if len(paths) != 1 {
		t.Fatalf("paths = %v, want one request", paths)
	}
}

type roundTripFunc func(*http.Request) (*http.Response, error)

func (f roundTripFunc) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }

func testJWT(t *testing.T, claims map[string]any) string {
	t.Helper()
	payload, err := json.Marshal(claims)
	if err != nil {
		t.Fatal(err)
	}
	return "e30." + base64.RawURLEncoding.EncodeToString(payload) + ".sig"
}
