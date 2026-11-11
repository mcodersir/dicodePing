// Package guardian is the client for Mozilla's Guardian API: it issues
// the ProxyPass bearer token for the Fastly CONNECT proxies, reports quota
// usage, and activates or reports the account's proxy entitlement.
package guardian

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"

	"dicodeping/fox/internal/controlplane"
)

// DefaultEndpoint is the production Guardian endpoint, matching Firefox's
// browser.ipProtection.guardian.endpoint preference.
const DefaultEndpoint = "https://vpn.mozilla.org"

type Entitlement struct {
	Subscribed       bool   `json:"subscribed"`
	UID              int    `json:"uid"`
	MaxBytes         string `json:"maxBytes"`
	LimitedBandwidth bool   `json:"limited_bandwidth"`
}

type proxyPassResponse struct {
	Token string `json:"token"`
}

// applyGuardianHeaders sets the request shape Firefox uses for every
// Guardian call: bearer auth, JSON content type, and fetch's "no-cache"
// mode, which Firefox sends as Cache-Control: max-age=0 (no Pragma).
func applyGuardianHeaders(req *http.Request, accessToken string) {
	req.Header.Set("Authorization", "Bearer "+accessToken)
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Cache-Control", "max-age=0")
	controlplane.ApplyFirefoxHeaders(req)
}

func guardianURL(endpoint, path string) string {
	if endpoint == "" {
		endpoint = DefaultEndpoint
	}
	return strings.TrimRight(endpoint, "/") + path
}

func fetchProxyPass(ctx context.Context, endpoint, accessToken string) (*ProxyPassInfo, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, guardianURL(endpoint, "/api/v1/fpn/token"), nil)
	if err != nil {
		return nil, err
	}
	applyGuardianHeaders(req, accessToken)

	resp, err := do(req)
	if err != nil {
		return nil, fmt.Errorf("guardian request failed: %w", err)
	}
	defer resp.Body.Close()
	receivedAt := time.Now()

	if resp.StatusCode != http.StatusOK {
		return nil, newHTTPError("guardian", resp)
	}

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("reading guardian response: %w", err)
	}

	var passResp proxyPassResponse
	if err := json.Unmarshal(body, &passResp); err != nil {
		return nil, &proxyPassFormatError{fmt.Errorf("parsing proxy pass response: %w", err)}
	}
	if passResp.Token == "" {
		return nil, &proxyPassFormatError{fmt.Errorf("empty token in guardian response")}
	}

	claims, err := parseJWTClaims(passResp.Token)
	if err != nil {
		return nil, &proxyPassFormatError{fmt.Errorf("parsing JWT claims: %w", err)}
	}
	offset, err := anchorProxyPassClaims(*claims, receivedAt)
	if err != nil {
		return nil, &proxyPassFormatError{err}
	}

	usage, usageErr := parseProxyUsage(resp.Header)
	info := &ProxyPassInfo{
		RawToken:        passResp.Token,
		Claims:          *claims,
		QuotaMax:        resp.Header.Get("X-Quota-Limit"),
		QuotaLeft:       resp.Header.Get("X-Quota-Remaining"),
		QuotaReset:      resp.Header.Get("X-Quota-Reset"),
		Usage:           usage,
		UsageErr:        usageErr,
		ReceivedAt:      receivedAt,
		claimTimeOffset: offset,
	}
	return info, nil
}

// fetchProxyUsage reads the quota headers from the token endpoint.
func fetchProxyUsage(ctx context.Context, method, endpoint, accessToken string) (*ProxyUsage, error) {
	req, err := http.NewRequestWithContext(ctx, method, guardianURL(endpoint, "/api/v1/fpn/token"), nil)
	if err != nil {
		return nil, err
	}
	applyGuardianHeaders(req, accessToken)

	resp, err := do(req)
	if err != nil {
		return nil, fmt.Errorf("guardian usage request failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		httpErr := newHTTPError("guardian usage", resp)
		if resp.StatusCode == http.StatusTooManyRequests && httpErr.Usage != nil {
			// A spent quota still reports valid usage headers.
			return httpErr.Usage, nil
		}
		return nil, httpErr
	}
	return parseProxyUsage(resp.Header)
}

func fetchUserInfo(ctx context.Context, endpoint, accessToken string) (*Entitlement, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, guardianURL(endpoint, "/api/v1/fpn/status"), nil)
	if err != nil {
		return nil, err
	}
	applyGuardianHeaders(req, accessToken)

	resp, err := do(req)
	if err != nil {
		return nil, fmt.Errorf("guardian user info request failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil, newHTTPError("guardian user info", resp)
	}

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, err
	}

	var ent Entitlement
	if err := json.Unmarshal(body, &ent); err != nil {
		return nil, fmt.Errorf("parsing entitlement: %w", err)
	}
	return &ent, nil
}

func activateGuardian(ctx context.Context, endpoint, accessToken string) (*Entitlement, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, guardianURL(endpoint, "/api/v1/fpn/activate"), nil)
	if err != nil {
		return nil, err
	}
	applyGuardianHeaders(req, accessToken)

	resp, err := do(req)
	if err != nil {
		return nil, fmt.Errorf("guardian activate request failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil, newHTTPError("guardian activate", resp)
	}

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, err
	}

	var ent Entitlement
	if err := json.Unmarshal(body, &ent); err != nil {
		return nil, fmt.Errorf("parsing activation entitlement: %w", err)
	}
	return &ent, nil
}

func FetchProxyPass(ctx context.Context, endpoint, accessToken string) (*ProxyPassInfo, error) {
	return fetchProxyPass(ctx, endpoint, accessToken)
}

// FetchProxyUsage returns the account's quota state without minting a pass.
func FetchProxyUsage(ctx context.Context, endpoint, accessToken string) (*ProxyUsage, error) {
	return fetchProxyUsage(ctx, http.MethodHead, endpoint, accessToken)
}

// RefreshProxyUsage handles an explicit quota refresh. If HEAD is refused,
// read the quota headers from a pass request and discard the pass itself.
func RefreshProxyUsage(ctx context.Context, endpoint, accessToken string) (*ProxyUsage, error) {
	usage, err := FetchProxyUsage(ctx, endpoint, accessToken)
	if errors.Is(err, ErrNotEntitled) {
		usage, err = fetchProxyUsage(ctx, http.MethodGet, endpoint, accessToken)
		if errors.Is(err, ErrNotEntitled) {
			return nil, fmt.Errorf("Mozilla denied access to this account's VPN quota (HTTP 403): %w", ErrNotEntitled)
		}
	}
	return usage, err
}

func FetchUserInfo(ctx context.Context, endpoint, accessToken string) (*Entitlement, error) {
	return fetchUserInfo(ctx, endpoint, accessToken)
}

func Activate(ctx context.Context, endpoint, accessToken string) (*Entitlement, error) {
	return activateGuardian(ctx, endpoint, accessToken)
}
