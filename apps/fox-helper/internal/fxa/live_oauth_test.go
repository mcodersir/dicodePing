//go:build live

package fxa

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"testing"
	"time"

	"dicodeping/fox/internal/guardian"
	"dicodeping/fox/internal/securefile"
)

// Explicit opt-in only: refreshes the OAuth credentials of one stored
// account (FXA_LIVE_CREDENTIALS = path of its credentials.json), writes the
// refreshed tokens back (keeping the other fields, such as the encrypted
// password), then verifies them against Guardian. It never logs access,
// refresh, session or ProxyPass tokens.
func TestLiveOAuthRefresh(t *testing.T) {
	path := os.Getenv("FXA_LIVE_CREDENTIALS")
	if os.Getenv("VPN_LIVE_AUTH_TEST") != "1" || path == "" {
		t.Skip("set VPN_LIVE_AUTH_TEST=1 and FXA_LIVE_CREDENTIALS=<data>/accounts/<id>/credentials.json")
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("reading the credentials failed: %T", err)
	}
	var fields map[string]any
	var saved SavedTokens
	if json.Unmarshal(raw, &fields) != nil || json.Unmarshal(raw, &saved) != nil || saved.RefreshToken == "" {
		t.Fatal("no readable refresh token; credentials omitted")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 100*time.Second)
	defer cancel()
	token, err := RefreshToken(ctx, saved.RefreshToken)
	if err != nil {
		var apiError *fxaAPIError
		if errors.As(err, &apiError) {
			t.Fatalf("FxA refresh rejected: HTTP=%d errno=%d (body omitted)", apiError.Status, apiError.Errno)
		}
		t.Fatalf("FxA refresh failed: %T (details omitted)", err)
	}
	if token.AccessToken == "" || token.ExpiresIn <= 0 {
		t.Fatal("FxA returned incomplete credentials; values omitted")
	}
	fields["access_token"], fields["expires_in"], fields["obtained_at"] = token.AccessToken, token.ExpiresIn, time.Now()
	if token.RefreshToken != "" {
		fields["refresh_token"] = token.RefreshToken
	}
	data, _ := json.MarshalIndent(fields, "", "  ")
	if err := securefile.WritePrivate(path, append(data, '\n')); err != nil {
		t.Fatalf("saving refreshed credentials failed: %T", err)
	}
	pass, err := guardian.FetchProxyPass(ctx, guardian.DefaultEndpoint, token.AccessToken)
	if err != nil {
		t.Fatalf("Guardian rejected or could not use refreshed OAuth credentials: %T (details omitted)", err)
	}
	if !pass.ExpiresAt().After(time.Now()) {
		t.Fatal("Guardian response does not contain a currently valid ProxyPass")
	}
	t.Logf("live OAuth refresh accepted; access_changed=%t expires_in=%d; saved=true; Guardian accepted the refreshed access; proxy_pass_expiry=%s", token.AccessToken != saved.AccessToken, token.ExpiresIn, pass.ExpiresAt().Format(time.RFC3339))
}
