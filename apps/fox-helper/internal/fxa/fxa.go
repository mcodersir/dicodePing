// Package fxa implements the Firefox Accounts client: password login with
// HAWK-authenticated session calls, sign-in verification, OAuth token
// issuance and refresh, the Fastly anti-bot challenge that guards the
// account API, and the local OAuth token cache.
package fxa

import (
	"context"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"

	"dicodeping/fox/internal/controlplane"
	"dicodeping/fox/internal/logx"
)

const (
	fxaAuthServer    = "https://api.accounts.firefox.com/v1"
	fxaOAuthTokenURL = "https://oauth.accounts.firefox.com/v1/token"
	firefoxClientID  = "5882386c6d801776"
	oauthScope       = "profile https://identity.mozilla.com/apps/vpn"

	// maxChallengeAttempts bounds how many times an FxA call re-solves the
	// Fastly anti-bot challenge; with rotating-exit proxies a solved cookie
	// can be rejected when the API request leaves through another IP.
	maxChallengeAttempts = 5

	// fxaChallengeBudget bounds recovery after the first 406, including
	// the fallback, solving, and the final retry.
	fxaChallengeBudget = 90 * time.Second

	// verificationMethodEmail2FA tells FxA to deliver the sign-in
	// confirmation as a code emailed to the account instead of the
	// default confirmation link: the link redirects through
	// accounts.firefox.com, which warns about non-Firefox browsers and
	// cannot be followed from this CLI client.
	verificationMethodEmail2FA = "email-2fa"

	// fxaErrnoInvalidParameter is FxA's "Invalid parameter" errno; a
	// deployment that does not accept verificationMethod in the login
	// body answers with it, so we fall back to a plain login.
	fxaErrnoInvalidParameter = 107
	fxaErrnoInvalidToken     = 108

	// fxaErrnoIncorrectEmailCase is FxA's "Incorrect email case" errno: the
	// email was typed in another letter case than the account's, which the
	// password's key stretching depends on. The error names the account's
	// own spelling.
	fxaErrnoIncorrectEmailCase = 120
)

type LoginResponse struct {
	SessionToken       string `json:"sessionToken"`
	UID                string `json:"uid"`
	Verified           bool   `json:"verified"`
	AuthAt             int64  `json:"authAt"`
	VerificationMethod string `json:"verificationMethod"`
	VerificationReason string `json:"verificationReason"`

	// Email is the email the sign-in succeeded with, in the account's own
	// letter case.
	Email string `json:"-"`
}

type TokenResponse struct {
	AccessToken  string `json:"access_token"`
	RefreshToken string `json:"refresh_token"`
	ExpiresIn    int    `json:"expires_in"`
	Scope        string `json:"scope"`
	TokenType    string `json:"token_type"`
}

// fxaAPIError carries a non-2xx FxA response so callers can branch on the
// API errno (e.g. invalid parameter) instead of parsing error strings.
type fxaAPIError struct {
	Status int
	Errno  int
	Body   string
	// Email is the account's email as FxA stores it, which sign-in errors
	// carry.
	Email string
}

func (e *fxaAPIError) Error() string {
	if e.Errno != 0 {
		return fmt.Sprintf("FxA error (HTTP %d, errno %d): %s", e.Status, e.Errno, e.Body)
	}
	return fmt.Sprintf("FxA request failed (HTTP %d): %s", e.Status, e.Body)
}

// ErrReauthRequired signals that FxA permanently rejected the stored
// credential (refresh token or session token), e.g. after the session was
// revoked server-side. Retrying cannot help; the user must sign in again.
var ErrReauthRequired = errors.New("Firefox Account sign-in required")

// Is lets errors.Is match ErrReauthRequired for credential rejections. FxA
// answers an invalid or revoked token with HTTP 400 (invalid_grant), 401,
// or 403; HTTP 429 and 5xx stay transient.
func (e *fxaAPIError) Is(target error) bool {
	if target != ErrReauthRequired {
		return false
	}
	switch e.Status {
	case http.StatusBadRequest, http.StatusUnauthorized, http.StatusForbidden:
		return e.Errno != fxaErrnoInvalidParameter
	}
	return false
}

func newFxaAPIError(status int, body []byte) *fxaAPIError {
	var parsed struct {
		Errno int    `json:"errno"`
		Email string `json:"email"`
	}
	_ = json.Unmarshal(body, &parsed)
	return &fxaAPIError{Status: status, Errno: parsed.Errno, Body: string(body), Email: parsed.Email}
}

// emailCaseError is the error of a sign-in repeated in the account's own
// letter case that still failed (for example blocked until an unblock
// code); it keeps that spelling for the next attempts.
type emailCaseError struct {
	email string
	err   error
}

func (e *emailCaseError) Error() string { return e.err.Error() }
func (e *emailCaseError) Unwrap() error { return e.err }

// fxaDo sends an FxA API request built by newRequest, transparently solving
// the Fastly anti-bot client challenge when the edge answers HTTP 406 (empty
// body, no FxA error payload). The request factory is invoked again after
// each successful solve because request bodies are single-use readers.
// ErrChallengeBlocked marks a call Fastly's bot check refused for good:
// its challenge could not be solved, or HTTP 406 kept coming back.
// Surfaces suggest the app's browser sign-in when they see it.
var ErrChallengeBlocked = errors.New("Mozilla's security check refused this sign-in from this program")

func fxaDo(ctx context.Context, newRequest func() (*http.Request, error)) (*http.Response, error) {
	return fxaDoWith406Fallback(ctx, newRequest, nil)
}

type requestTimeoutKey struct{}

// WithRequestTimeout limits the first HTTP attempt of each FxA call.
// The caller's context still governs the whole operation, including recovery.
func WithRequestTimeout(ctx context.Context, timeout time.Duration) context.Context {
	return context.WithValue(ctx, requestTimeoutKey{}, timeout)
}

type fxaResponseBody struct {
	io.ReadCloser
	cancel context.CancelFunc
}

func (b *fxaResponseBody) Close() error {
	defer b.cancel()
	return b.ReadCloser.Close()
}

// on406 can try an alternate request when the original returns 406. It
// receives the number of completed challenge solves. A nil response and
// error leave the original challenge path available.
func fxaDoWith406Fallback(ctx context.Context, newRequest func() (*http.Request, error), on406 func(context.Context, int) (*http.Response, error)) (response *http.Response, err error) {
	requestCtx := ctx
	var cancel context.CancelFunc
	if timeout, ok := ctx.Value(requestTimeoutKey{}).(time.Duration); ok {
		requestCtx, cancel = context.WithTimeout(ctx, timeout)
	}
	defer func() {
		if cancel == nil {
			return
		}
		if response == nil {
			cancel()
			return
		}
		// The caller still needs the request context to read the body.
		response.Body = &fxaResponseBody{ReadCloser: response.Body, cancel: cancel}
	}()

	for solved := 0; ; solved++ {
		req, err := newRequest()
		if err != nil {
			return nil, err
		}
		resp, err := controlplane.Do(req.WithContext(requestCtx))
		if err != nil {
			if solved > 0 {
				logx.Warn("FxA API retry ended without an HTTP response method=%s host=%s path=%s solves=%d", req.Method, req.URL.Hostname(), req.URL.Path, solved)
			}
			return nil, err
		}
		if solved > 0 {
			logx.Info("FxA API retry returned HTTP %d method=%s host=%s path=%s solves=%d", resp.StatusCode, req.Method, req.URL.Hostname(), req.URL.Path, solved)
		}
		if resp.StatusCode != http.StatusNotAcceptable {
			return resp, nil
		}
		io.Copy(io.Discard, io.LimitReader(resp.Body, 4096))
		resp.Body.Close()

		if solved == 0 {
			if cancel != nil {
				cancel()
			}
			recoveryCtx, finishRecovery := context.WithTimeout(ctx, fxaChallengeBudget)
			requestCtx, cancel = recoveryCtx, finishRecovery
		}
		if on406 != nil {
			if alternate, err := on406(requestCtx, solved); alternate != nil || err != nil {
				return alternate, err
			}
		}
		if solved == maxChallengeAttempts {
			return nil, fmt.Errorf("%w: still HTTP 406 after %d solved challenges", ErrChallengeBlocked, solved)
		}

		logx.Info("the account server answered HTTP 406 (Fastly's bot check); solving its challenge attempt=%d", solved+1)
		if err := solveFastlyChallenge(requestCtx); err != nil {
			if requestCtx.Err() != nil {
				return nil, requestCtx.Err()
			}
			logx.Warn("Fastly challenge failed attempt=%d err=%s", solved+1, logx.Err(err))
			return nil, fmt.Errorf("%w: its challenge failed: %w", ErrChallengeBlocked, err)
		}
	}
}

// fxaLogin signs in. An email typed in another letter case than the
// account's is refused with the account's own spelling (errno 120); the
// sign-in is then repeated once with it, as Firefox does, naming the typed
// email as originalLoginEmail.
func fxaLogin(ctx context.Context, email, password, unblockCode string) (*LoginResponse, error) {
	resp, err := fxaLoginAs(ctx, email, "", password, unblockCode)
	var apiErr *fxaAPIError
	if errors.As(err, &apiErr) && apiErr.Errno == fxaErrnoIncorrectEmailCase && apiErr.Email != "" && apiErr.Email != email {
		resp, err = fxaLoginAs(ctx, apiErr.Email, email, password, unblockCode)
		if err != nil {
			return nil, &emailCaseError{email: apiErr.Email, err: err}
		}
	}
	return resp, err
}

// fxaLoginAs signs in as email; a deployment that does not accept the
// verification method is asked again without it.
func fxaLoginAs(ctx context.Context, email, originalEmail, password, unblockCode string) (*LoginResponse, error) {
	resp, err := fxaLoginAttempt(ctx, email, originalEmail, password, verificationMethodEmail2FA, unblockCode)
	var apiErr *fxaAPIError
	if errors.As(err, &apiErr) && apiErr.Errno == fxaErrnoInvalidParameter {
		resp, err = fxaLoginAttempt(ctx, email, originalEmail, password, "", unblockCode)
	}
	if err != nil {
		return nil, err
	}
	resp.Email = email
	return resp, nil
}

func fxaLoginAttempt(ctx context.Context, email, originalEmail, password, verificationMethod, unblockCode string) (*LoginResponse, error) {
	authPW, err := deriveAuthPW(email, password)
	if err != nil {
		return nil, fmt.Errorf("deriving authPW: %w", err)
	}

	body := map[string]string{
		"email":  email,
		"authPW": hex.EncodeToString(authPW),
	}
	if originalEmail != "" {
		body["originalLoginEmail"] = originalEmail
	}
	if verificationMethod != "" {
		body["verificationMethod"] = verificationMethod
	}
	if unblockCode != "" {
		body["unblockCode"] = unblockCode
	}
	bodyJSON, _ := json.Marshal(body)

	loginURL := fxaAuthServer + "/account/login"

	resp, err := fxaDo(ctx, func() (*http.Request, error) {
		req, err := http.NewRequestWithContext(ctx, http.MethodPost, loginURL, strings.NewReader(string(bodyJSON)))
		if err != nil {
			return nil, fmt.Errorf("creating login request: %w", err)
		}
		req.Header.Set("Content-Type", "application/json")
		controlplane.ApplyFirefoxHeaders(req)
		return req, nil
	})
	if err != nil {
		return nil, fmt.Errorf("login request: %w", err)
	}
	defer resp.Body.Close()

	data, _ := io.ReadAll(resp.Body)
	if resp.StatusCode != http.StatusOK {
		return nil, newFxaAPIError(resp.StatusCode, data)
	}

	var loginResp LoginResponse
	if err := json.Unmarshal(data, &loginResp); err != nil {
		return nil, fmt.Errorf("parsing login response: %w", err)
	}
	return &loginResp, nil
}

// fxaVerifySession submits the email confirmation code for an unverified
// session created by fxaLogin; FxA sends the code to the account email at
// login time.
func fxaVerifySession(ctx context.Context, sessionToken, code string) error {
	hawkID, hawkKey, err := deriveHawkCredentials(sessionToken, "sessionToken")
	if err != nil {
		return fmt.Errorf("deriving hawk credentials: %w", err)
	}

	body := map[string]string{"code": code}
	bodyJSON, _ := json.Marshal(body)
	verifyURL := fxaAuthServer + "/session/verify_code"

	resp, err := fxaDo(ctx, func() (*http.Request, error) {
		authHeader, err := hawkHeader("POST", verifyURL, hawkID, hawkKey, string(bodyJSON))
		if err != nil {
			return nil, fmt.Errorf("generating hawk header: %w", err)
		}
		req, err := http.NewRequestWithContext(ctx, http.MethodPost, verifyURL, strings.NewReader(string(bodyJSON)))
		if err != nil {
			return nil, fmt.Errorf("creating verify code request: %w", err)
		}
		req.Header.Set("Content-Type", "application/json")
		req.Header.Set("Authorization", authHeader)
		controlplane.ApplyFirefoxHeaders(req)
		return req, nil
	})
	if err != nil {
		return fmt.Errorf("verify code request: %w", err)
	}
	defer resp.Body.Close()

	data, _ := io.ReadAll(resp.Body)
	if resp.StatusCode != http.StatusOK {
		return newFxaAPIError(resp.StatusCode, data)
	}
	return nil
}

// SessionVerified reports whether the session is confirmed: the account's
// email is verified and so is this sign-in (any code it asked for, by
// email or from an authenticator, was entered). It asks
// /recovery_email/status, as Firefox does while a sign-in it was handed
// waits for its code.
func SessionVerified(ctx context.Context, sessionToken string) (bool, error) {
	hawkID, hawkKey, err := deriveHawkCredentials(sessionToken, "sessionToken")
	if err != nil {
		return false, fmt.Errorf("deriving hawk credentials: %w", err)
	}
	statusURL := fxaAuthServer + "/recovery_email/status"
	resp, err := fxaDo(ctx, func() (*http.Request, error) {
		authHeader, err := hawkHeader(http.MethodGet, statusURL, hawkID, hawkKey, "")
		if err != nil {
			return nil, fmt.Errorf("generating hawk header: %w", err)
		}
		req, err := http.NewRequestWithContext(ctx, http.MethodGet, statusURL, nil)
		if err != nil {
			return nil, fmt.Errorf("creating session status request: %w", err)
		}
		req.Header.Set("Authorization", authHeader)
		controlplane.ApplyFirefoxHeaders(req)
		return req, nil
	})
	if err != nil {
		return false, fmt.Errorf("session status request: %w", err)
	}
	defer resp.Body.Close()
	data, _ := io.ReadAll(io.LimitReader(resp.Body, 16<<10))
	if resp.StatusCode != http.StatusOK {
		return false, newFxaAPIError(resp.StatusCode, data)
	}
	var status struct {
		Verified *bool `json:"verified"`
	}
	if err := json.Unmarshal(data, &status); err != nil || status.Verified == nil {
		return false, errors.New("unexpected session status response")
	}
	return *status.Verified, nil
}

// DestroySession ends a session token once its OAuth tokens are issued.
// Left alive, it stays in the account's connected services as an
// "unknown" session next to the device record; the program needs only the
// refresh token for background OAuth renewal.
func DestroySession(ctx context.Context, sessionToken string) error {
	hawkID, hawkKey, err := deriveHawkCredentials(sessionToken, "sessionToken")
	if err != nil {
		return fmt.Errorf("deriving hawk credentials: %w", err)
	}
	const body = "{}"
	destroyURL := fxaAuthServer + "/session/destroy"
	resp, err := fxaDo(ctx, func() (*http.Request, error) {
		authHeader, err := hawkHeader("POST", destroyURL, hawkID, hawkKey, body)
		if err != nil {
			return nil, fmt.Errorf("generating hawk header: %w", err)
		}
		req, err := http.NewRequestWithContext(ctx, http.MethodPost, destroyURL, strings.NewReader(body))
		if err != nil {
			return nil, fmt.Errorf("creating session destroy request: %w", err)
		}
		req.Header.Set("Content-Type", "application/json")
		req.Header.Set("Authorization", authHeader)
		controlplane.ApplyFirefoxHeaders(req)
		return req, nil
	})
	if err != nil {
		return fmt.Errorf("session destroy request: %w", err)
	}
	defer resp.Body.Close()
	data, _ := io.ReadAll(resp.Body)
	if resp.StatusCode != http.StatusOK {
		return newFxaAPIError(resp.StatusCode, data)
	}
	return nil
}

func fxaOAuthToken(ctx context.Context, sessionToken string, sendHTTP2 func(*http.Request) (*http.Response, error)) (*TokenResponse, error) {
	hawkID, hawkKey, err := deriveHawkCredentials(sessionToken, "sessionToken")
	if err != nil {
		return nil, fmt.Errorf("deriving hawk credentials: %w", err)
	}

	body := map[string]interface{}{
		"client_id":   firefoxClientID,
		"grant_type":  "fxa-credentials",
		"scope":       oauthScope,
		"access_type": "offline",
	}
	bodyJSON, _ := json.Marshal(body)

	tokenURL := fxaAuthServer + "/oauth/token"

	newRequest := func(ctx context.Context) (*http.Request, error) {
		authHeader, err := hawkHeader("POST", tokenURL, hawkID, hawkKey, string(bodyJSON))
		if err != nil {
			return nil, fmt.Errorf("generating hawk header: %w", err)
		}
		req, err := newOAuthJSONRequest(ctx, tokenURL, bodyJSON)
		if err != nil {
			return nil, fmt.Errorf("creating oauth token request: %w", err)
		}
		req.Header.Set("Authorization", authHeader)
		return req, nil
	}
	resp, err := fxaDoWith406Fallback(ctx, func() (*http.Request, error) {
		return newRequest(ctx)
	}, func(ctx context.Context, solved int) (*http.Response, error) {
		if sendHTTP2 != nil && solved <= 1 {
			if response, err := tryOAuthTokenHTTP2(ctx, newRequest, sendHTTP2); response != nil || err != nil {
				return response, err
			}
		}
		return exchangeSessionWithOAuthCode(ctx, hawkID, hawkKey)
	})
	if err != nil {
		return nil, fmt.Errorf("oauth token request: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil, newFxaAPIError(resp.StatusCode, []byte(controlplane.ReadErrorBody(resp.Body)))
	}
	data, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("reading token response: %w", err)
	}

	var tok TokenResponse
	if err := json.Unmarshal(data, &tok); err != nil {
		return nil, fmt.Errorf("parsing token response: %w", err)
	}
	if tok.AccessToken == "" || tok.RefreshToken == "" {
		return nil, errors.New("OAuth sign-in response is missing account tokens")
	}
	return &tok, nil
}

// tryOAuthTokenHTTP2 repeats the same grant over HTTP/2. If that transport
// cannot reach FxA or is also challenged, the existing recovery can continue.
func tryOAuthTokenHTTP2(ctx context.Context, newRequest func(context.Context) (*http.Request, error), send func(*http.Request) (*http.Response, error)) (*http.Response, error) {
	req, err := newRequest(ctx)
	if err != nil {
		return nil, err
	}
	resp, err := send(req)
	if err != nil {
		if ctx.Err() != nil {
			return nil, ctx.Err()
		}
		if !errors.Is(err, controlplane.ErrDirectHTTP2Unavailable) {
			logx.Info("direct OAuth HTTP/2 retry ended without an HTTP response")
		}
		return nil, nil
	}
	logx.Info("direct OAuth HTTP/2 retry returned HTTP %d", resp.StatusCode)
	if resp.StatusCode == http.StatusNotAcceptable {
		resp.Body.Close()
		return nil, nil
	}
	return resp, nil
}

func fxaRefreshToken(ctx context.Context, refreshToken string) (*TokenResponse, error) {
	// Scope is optional for refresh grants. Mozilla defaults it to the
	// stored grant; repeating the VPN scope can trigger an edge 406.
	// Do not renegotiate permissions during access renewal.
	body := map[string]interface{}{
		"client_id":     firefoxClientID,
		"grant_type":    "refresh_token",
		"refresh_token": refreshToken,
	}
	bodyJSON, _ := json.Marshal(body)

	newRequest := func(tokenURL string) (*http.Request, error) {
		req, err := http.NewRequestWithContext(ctx, http.MethodPost, tokenURL, strings.NewReader(string(bodyJSON)))
		if err != nil {
			return nil, fmt.Errorf("creating refresh request: %w", err)
		}
		req.Header.Set("Content-Type", "application/json")
		controlplane.ApplyFirefoxHeaders(req)
		return req, nil
	}
	resp, err := fxaDoWith406Fallback(ctx, func() (*http.Request, error) {
		return newRequest(fxaAuthServer + "/oauth/token")
	}, func(ctx context.Context, solved int) (*http.Response, error) {
		if solved != 0 {
			return nil, nil
		}
		req, err := newRequest(fxaOAuthTokenURL)
		if err != nil {
			return nil, err
		}
		return refreshAtOAuthEndpoint(req.WithContext(ctx))
	})
	if err != nil {
		return nil, fmt.Errorf("refresh request: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil, newFxaAPIError(resp.StatusCode, []byte(controlplane.ReadErrorBody(resp.Body)))
	}
	data, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("reading refresh response: %w", err)
	}

	var tok TokenResponse
	if err := json.Unmarshal(data, &tok); err != nil {
		return nil, fmt.Errorf("parsing refresh response: %w", err)
	}
	// Refresh response may not include a new refresh_token; keep the old one
	if tok.RefreshToken == "" {
		tok.RefreshToken = refreshToken
	}
	return &tok, nil
}

// Both Mozilla token endpoints use the same refresh-token store. The
// OAuth endpoint cannot exchange the Hawk session credential used at sign-in.
func refreshAtOAuthEndpoint(req *http.Request) (*http.Response, error) {
	resp, err := controlplane.Do(req)
	if err != nil {
		return nil, nil
	}
	if resp.StatusCode == http.StatusOK {
		logx.Info("OAuth refresh accepted by Mozilla's OAuth endpoint after HTTP 406")
		return resp, nil
	}
	defer resp.Body.Close()
	switch resp.StatusCode {
	case http.StatusNotAcceptable:
		return nil, nil
	case http.StatusBadRequest:
		apiErr := newFxaAPIError(resp.StatusCode, []byte(controlplane.ReadErrorBody(resp.Body)))
		if apiErr.Errno == fxaErrnoInvalidToken {
			apiErr.Body = "invalid refresh token"
			return nil, apiErr
		}
	}
	return nil, fmt.Errorf("Mozilla's OAuth endpoint returned HTTP %d", resp.StatusCode)
}

func Login(ctx context.Context, email, password string) (*LoginResponse, error) {
	return fxaLogin(ctx, email, password, "")
}

func VerifySession(ctx context.Context, sessionToken, code string) error {
	return fxaVerifySession(ctx, sessionToken, NormalizeCode(code))
}

func OAuthToken(ctx context.Context, sessionToken string) (*TokenResponse, error) {
	return fxaOAuthToken(ctx, sessionToken, nil)
}

// OAuthTokenDirect enables the HTTP/2 fallback for an interactive direct sign-in.
func OAuthTokenDirect(ctx context.Context, sessionToken string) (*TokenResponse, error) {
	return fxaOAuthToken(ctx, sessionToken, controlplane.DoDirectHTTP2)
}

func RefreshToken(ctx context.Context, refreshToken string) (*TokenResponse, error) {
	return fxaRefreshToken(ctx, refreshToken)
}
