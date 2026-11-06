package fxa

import (
	"bytes"
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"

	"dicodeping/fox/internal/controlplane"
	"dicodeping/fox/internal/logx"
)

// exchangeSessionWithOAuthCode uses FxA's session-authenticated code grant
// when the direct session-to-token exchange is refused at the edge.
func exchangeSessionWithOAuthCode(ctx context.Context, hawkID string, hawkKey []byte) (*http.Response, error) {
	var secret [32]byte
	if _, err := rand.Read(secret[:]); err != nil {
		return nil, fmt.Errorf("generating OAuth code verifier: %w", err)
	}
	verifier := base64.RawURLEncoding.EncodeToString(secret[:])
	challenge := sha256.Sum256([]byte(verifier))
	state := rand.Text()

	const authorizeURL = fxaAuthServer + "/oauth/authorization"
	authorizeBody, _ := json.Marshal(map[string]string{
		"client_id":             firefoxClientID,
		"response_type":         "code",
		"scope":                 oauthScope,
		"state":                 state,
		"access_type":           "offline",
		"code_challenge":        base64.RawURLEncoding.EncodeToString(challenge[:]),
		"code_challenge_method": "S256",
	})
	authorizeRequest, err := newOAuthJSONRequest(ctx, authorizeURL, authorizeBody)
	if err != nil {
		return nil, fmt.Errorf("creating OAuth authorization request: %w", err)
	}
	header, err := hawkHeader(http.MethodPost, authorizeURL, hawkID, hawkKey, string(authorizeBody))
	if err != nil {
		return nil, fmt.Errorf("signing OAuth authorization request: %w", err)
	}
	authorizeRequest.Header.Set("Authorization", header)
	resp, err := controlplane.Do(authorizeRequest)
	if err != nil {
		return nil, fmt.Errorf("requesting OAuth authorization code: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode == http.StatusNotAcceptable {
		// The original token request and this alternate grant share recovery.
		logx.Info("OAuth authorization returned HTTP 406")
		return nil, nil
	}
	if resp.StatusCode != http.StatusOK {
		return nil, oauthCodeError(resp, "OAuth authorization")
	}
	var authorization struct {
		Code  string `json:"code"`
		State string `json:"state"`
	}
	if err := json.NewDecoder(io.LimitReader(resp.Body, 16<<10)).Decode(&authorization); err != nil || authorization.Code == "" || authorization.State != state {
		return nil, errors.New("invalid OAuth authorization response")
	}

	tokenBody, _ := json.Marshal(map[string]string{
		"client_id":     firefoxClientID,
		"grant_type":    "authorization_code",
		"code":          authorization.Code,
		"code_verifier": verifier,
	})
	req, err := newOAuthJSONRequest(ctx, fxaOAuthTokenURL, tokenBody)
	if err != nil {
		return nil, err
	}
	tokens, err := controlplane.Do(req)
	if err != nil {
		return nil, fmt.Errorf("exchanging OAuth authorization code: %w", err)
	}
	if tokens.StatusCode != http.StatusOK {
		defer tokens.Body.Close()
		if tokens.StatusCode == http.StatusNotAcceptable {
			return nil, nil // Let the original request use its challenge flow.
		}
		return nil, oauthCodeError(tokens, "OAuth authorization code exchange")
	}
	logx.Info("OAuth authorization code exchange accepted after sign-in HTTP 406")
	return tokens, nil
}

func newOAuthJSONRequest(ctx context.Context, target string, body []byte) (*http.Request, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, target, bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")
	controlplane.ApplyFirefoxHeaders(req)
	return req, nil
}

// OAuth errors may include the code or verifier. Retain the errno for
// callers that handle unverified sessions without exposing the body.
func oauthCodeError(resp *http.Response, step string) error {
	var data struct {
		Errno int `json:"errno"`
	}
	_ = json.NewDecoder(io.LimitReader(resp.Body, 4096)).Decode(&data)
	return &fxaAPIError{Status: resp.StatusCode, Errno: data.Errno, Body: step + " failed"}
}
