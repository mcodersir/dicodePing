package guardian

import (
	"encoding/json"
	"testing"
	"time"
)

func TestAnchorProxyPassClaimsKeepsAgreeingClocks(t *testing.T) {
	now := time.Date(2026, 7, 2, 22, 25, 50, 0, time.UTC)
	claims := ProxyPassClaims{
		Iat: now.Add(-30 * time.Second).Unix(),
		Nbf: now.Add(-30 * time.Second).Unix(),
		Exp: now.Add(10 * time.Minute).Unix(),
	}

	got, err := anchorProxyPassClaims(claims, now)
	if err != nil || got != 0 {
		t.Fatalf("expected raw claim times, got offset=%s err=%v", got, err)
	}
}

func TestAnchorProxyPassClaimsReanchorsSkewedClaimsToReceipt(t *testing.T) {
	// Guardian's claims are eight hours behind the local clock (e.g. a
	// local wall-clock time written as UTC): the pass is still valid from
	// receipt for its ten-minute lifetime, as Firefox computes it.
	now := time.Date(2026, 7, 2, 22, 25, 50, 0, time.UTC)
	claims := ProxyPassClaims{
		Iat: time.Date(2026, 7, 2, 14, 25, 34, 0, time.UTC).Unix(),
		Nbf: time.Date(2026, 7, 2, 14, 25, 34, 0, time.UTC).Unix(),
		Exp: time.Date(2026, 7, 2, 14, 35, 34, 0, time.UTC).Unix(),
	}

	offset, err := anchorProxyPassClaims(claims, now)
	if err != nil {
		t.Fatal(err)
	}
	pass := &ProxyPassInfo{Claims: claims, claimTimeOffset: offset}
	if want := now.Add(10 * time.Minute); !pass.ExpiresAt().Equal(want) {
		t.Fatalf("expected anchored expiry %s, got %s", want, pass.ExpiresAt())
	}
	if !pass.NotBefore().Equal(now) {
		t.Fatalf("expected pass to be valid from receipt %s, got %s", now, pass.NotBefore())
	}
}

func TestAnchorProxyPassClaimsUsesIssuedAtWhenNotBeforeMissing(t *testing.T) {
	now := time.Date(2026, 7, 2, 14, 36, 51, 0, time.UTC)
	claims := ProxyPassClaims{
		Iat: time.Date(2026, 7, 2, 22, 36, 35, 0, time.UTC).Unix(),
		Exp: time.Date(2026, 7, 2, 22, 46, 35, 0, time.UTC).Unix(),
	}

	offset, err := anchorProxyPassClaims(claims, now)
	if err != nil {
		t.Fatal(err)
	}
	pass := &ProxyPassInfo{Claims: claims, claimTimeOffset: offset}
	if want := now.Add(10 * time.Minute); !pass.ExpiresAt().Equal(want) {
		t.Fatalf("expected anchored expiry %s, got %s", want, pass.ExpiresAt())
	}
}

func TestAnchorProxyPassClaimsKeepsExpiryWithoutStartClaims(t *testing.T) {
	now := time.Date(2026, 7, 2, 22, 36, 51, 0, time.UTC)
	claims := ProxyPassClaims{Exp: now.Add(10 * time.Minute).Unix()}

	if got, err := anchorProxyPassClaims(claims, now); err != nil || got != 0 {
		t.Fatalf("expected raw expiry, got offset=%s err=%v", got, err)
	}
}

func TestAnchorProxyPassClaimsRejectsUnusableClaims(t *testing.T) {
	now := time.Now()
	for name, claims := range map[string]ProxyPassClaims{
		"missing exp":      {Nbf: now.Unix()},
		"exp before start": {Nbf: now.Unix(), Exp: now.Add(-time.Minute).Unix()},
		"exp equals start": {Iat: now.Unix(), Exp: now.Unix()},
	} {
		if _, err := anchorProxyPassClaims(claims, now); err == nil {
			t.Fatalf("%s: expected an error", name)
		}
	}
}

func TestAudienceAcceptsStringAndArray(t *testing.T) {
	var single, many ProxyPassClaims
	if err := json.Unmarshal([]byte(`{"aud":"https://vpn.mozilla.org"}`), &single); err != nil || single.Aud != "https://vpn.mozilla.org" {
		t.Fatalf("string aud: %q %v", single.Aud, err)
	}
	if err := json.Unmarshal([]byte(`{"aud":["a","b"]}`), &many); err != nil || many.Aud != "a,b" {
		t.Fatalf("array aud: %q %v", many.Aud, err)
	}
}
