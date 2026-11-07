package fxa

import (
	"context"
	"dicodeping/fox/internal/controlplane"
	"encoding/json"
	"io"
	"net/http"
	"strings"
	"testing"
)

func TestRefreshUsesHTTP2After406AndKeepsRefreshCredential(t *testing.T) {
	old := controlplane.Transport()
	t.Cleanup(func() { controlplane.SetTransport(old) })
	calls := 0
	controlplane.SetTransport(roundTripFunc(func(r *http.Request) (*http.Response, error) {
		calls++
		return &http.Response{StatusCode: 406, Header: make(http.Header), Body: io.NopCloser(strings.NewReader("")), Request: r}, nil
	}))
	token, err := refreshTokenWithHTTP2(context.Background(), "refresh-fixture", func(r *http.Request) (*http.Response, error) {
		var body map[string]string
		json.NewDecoder(r.Body).Decode(&body)
		if r.URL.Host != "api.accounts.firefox.com" || r.URL.Path != "/v1/oauth/token" || body["refresh_token"] != "refresh-fixture" || body["grant_type"] != "refresh_token" || r.Header.Get("Accept-Encoding") != "identity" {
			t.Fatal("HTTP/2 retry changed the grant or headers")
		}
		return &http.Response{StatusCode: 200, Header: make(http.Header), Body: io.NopCloser(strings.NewReader(`{"access_token":"access-fixture","expires_in":3600}`)), Request: r}, nil
	})
	if err != nil || calls != 1 || token.RefreshToken != "refresh-fixture" || token.AccessToken != "access-fixture" {
		t.Fatalf("refresh recovery failed: %v", err)
	}
}
