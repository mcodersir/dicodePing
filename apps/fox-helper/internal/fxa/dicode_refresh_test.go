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

func TestRefreshDoesNotRenegotiateScopeAndKeepsCredential(t *testing.T) {
	old := controlplane.Transport()
	t.Cleanup(func() { controlplane.SetTransport(old) })
	controlplane.SetTransport(roundTripFunc(func(r *http.Request) (*http.Response, error) {
		var body map[string]string
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			t.Fatal(err)
		}
		if _, present := body["scope"]; present {
			t.Error("refresh must retain the stored scope rather than renegotiate it")
		}
		if body["grant_type"] != "refresh_token" || body["refresh_token"] != "refresh-fixture" || body["client_id"] != firefoxClientID || r.Header.Get("Accept-Encoding") != "identity" {
			t.Error("refresh grant changed")
		}
		return &http.Response{StatusCode: 200, Header: make(http.Header), Body: io.NopCloser(strings.NewReader(`{"access_token":"fresh-fixture","expires_in":3600}`)), Request: r}, nil
	}))
	token, err := fxaRefreshToken(context.Background(), "refresh-fixture")
	if err != nil {
		t.Fatal(err)
	}
	if token.RefreshToken != "refresh-fixture" || token.AccessToken != "fresh-fixture" || token.ExpiresIn != 3600 {
		t.Fatal("renewal lost the credential or expiry")
	}
}
