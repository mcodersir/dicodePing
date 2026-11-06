package guardian

import (
	"encoding/base64"
	"encoding/json"
	"fmt"
	"strings"
	"time"
)

// proxyPassClaimTimeTolerance is the clock disagreement between Guardian and
// this host that is tolerated before the pass lifetime is re-anchored to the
// local receipt time.
const proxyPassClaimTimeTolerance = time.Minute

// Audience is the JWT "aud" claim. Guardian issues a single URI, but the
// JWT specification also allows an array, which is joined with commas.
type Audience string

func (a *Audience) UnmarshalJSON(data []byte) error {
	var single string
	if err := json.Unmarshal(data, &single); err == nil {
		*a = Audience(single)
		return nil
	}
	var many []string
	if err := json.Unmarshal(data, &many); err != nil {
		return fmt.Errorf("aud claim must be a string or an array of strings")
	}
	*a = Audience(strings.Join(many, ","))
	return nil
}

type ProxyPassClaims struct {
	Sub string   `json:"sub"`
	Aud Audience `json:"aud"`
	Iat int64    `json:"iat"`
	Nbf int64    `json:"nbf"`
	Exp int64    `json:"exp"`
	Iss string   `json:"iss"`
}

type ProxyPassInfo struct {
	RawToken   string
	Claims     ProxyPassClaims
	QuotaMax   string
	QuotaLeft  string
	QuotaReset string
	// Usage is the parsed quota state, or nil when Guardian sent no valid
	// quota headers (UsageErr then explains why).
	Usage    *ProxyUsage
	UsageErr error
	// ReceivedAt is the local time the pass was received.
	ReceivedAt      time.Time
	claimTimeOffset time.Duration
}

func (p *ProxyPassInfo) NotBefore() time.Time { return p.claimTime(p.Claims.Nbf) }
func (p *ProxyPassInfo) ExpiresAt() time.Time { return p.claimTime(p.Claims.Exp) }

func (p *ProxyPassInfo) claimTime(sec int64) time.Time {
	return time.Unix(sec, 0).Add(p.claimTimeOffset)
}

// ClaimTimeCorrection reports how far the pass lifetime was shifted from the
// raw JWT claims to the local clock; zero when the clocks agree.
func (p *ProxyPassInfo) ClaimTimeCorrection() time.Duration {
	return p.claimTimeOffset
}

func (p *ProxyPassInfo) BearerToken() string { return "Bearer " + p.RawToken }

// anchorProxyPassClaims returns the shift applied to the JWT claim times.
// Like Firefox (bug 2054514), a pass is treated as valid from the moment it
// was received for its claimed lifetime (exp minus nbf, or minus iat), so
// clock drift between Guardian and this host cannot misplace renewal. While
// the clocks agree within proxyPassClaimTimeTolerance the raw claims are
// kept, which never extends a pass beyond its signed expiry.
func anchorProxyPassClaims(claims ProxyPassClaims, receivedAt time.Time) (time.Duration, error) {
	if claims.Exp <= 0 {
		return 0, fmt.Errorf("proxy pass has no exp claim")
	}
	start, hasStart := proxyPassClaimStartTime(claims)
	if !hasStart {
		// Without a start claim the lifetime is unknown; use exp as is.
		return 0, nil
	}
	if claims.Exp <= start.Unix() {
		return 0, fmt.Errorf("proxy pass exp claim is not after its start claim")
	}
	offset := receivedAt.Sub(start).Truncate(time.Second)
	if offset >= -proxyPassClaimTimeTolerance && offset <= proxyPassClaimTimeTolerance {
		return 0, nil
	}
	return offset, nil
}

func proxyPassClaimStartTime(claims ProxyPassClaims) (time.Time, bool) {
	switch {
	case claims.Nbf > 0:
		return time.Unix(claims.Nbf, 0), true
	case claims.Iat > 0:
		return time.Unix(claims.Iat, 0), true
	default:
		return time.Time{}, false
	}
}

func parseJWTClaims(token string) (*ProxyPassClaims, error) {
	parts := strings.Split(token, ".")
	if len(parts) != 3 {
		return nil, fmt.Errorf("invalid JWT: expected 3 parts, got %d", len(parts))
	}

	// JWT segments use unpadded base64url; tolerate stray padding.
	payload := strings.TrimRight(parts[1], "=")
	decoded, err := base64.RawURLEncoding.DecodeString(payload)
	if err != nil {
		return nil, fmt.Errorf("decoding JWT payload: %w", err)
	}

	var claims ProxyPassClaims
	if err := json.Unmarshal(decoded, &claims); err != nil {
		return nil, fmt.Errorf("parsing JWT claims JSON: %w", err)
	}
	return &claims, nil
}
