package proxy

import (
	"context"
	"dicodeping/fox/internal/controlplane"
	"dicodeping/fox/internal/fxa"
	"errors"
	"io"
	"net/http"
	"strings"
	"testing"
	"time"
)

func TestStartupRefreshFailureHonorsActualGrantExpiry(t *testing.T) {
	for _, tc := range []struct {
		name            string
		seconds         int
		revoked, usable bool
	}{
		{"still valid during transient failure", 90, false, true},
		{"expired remains rejected", -1, false, false},
		{"revoked remains rejected", 90, true, false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			previous := controlplane.Transport()
			t.Cleanup(func() { controlplane.SetTransport(previous) })
			controlplane.SetTransport(auditRoundTripper(func(r *http.Request) (*http.Response, error) {
				if !tc.revoked {
					return nil, errors.New("temporary transport failure")
				}
				return &http.Response{StatusCode: 401, Header: make(http.Header), Body: io.NopCloser(strings.NewReader(`{"errno":108}`)), Request: r}, nil
			}))
			saved := false
			auth := DicodeAuth(&fxa.TokenResponse{AccessToken: "valid-until-real-expiry", RefreshToken: "refresh-fixture", ExpiresIn: tc.seconds}, time.Now(), func(*fxa.TokenResponse) error { saved = true; return nil })
			got, err := FreshRuntimeAuth(context.Background(), auth)
			if tc.usable {
				if err != nil || got != auth {
					t.Fatalf("unexpired credential lost after proactive refresh: %v", err)
				}
			} else if err == nil {
				t.Fatal("expired or revoked credential was accepted")
			}
			if saved || auth.Token.ExpiresIn != tc.seconds {
				t.Fatal("failed refresh rewrote credential expiry")
			}
		})
	}
}
