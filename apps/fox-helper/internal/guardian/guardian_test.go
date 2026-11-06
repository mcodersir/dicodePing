package guardian

import (
	"encoding/base64"
	"encoding/json"
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
