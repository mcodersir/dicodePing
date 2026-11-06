package fxa

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"strings"

	"dicodeping/fox/internal/controlplane"
)

// ErrnoRequestBlocked is FxA's "request blocked" errno: the sign-in looks
// unusual (new location, many attempts) and must be repeated with an unblock
// code that FxA emails on request.
const ErrnoRequestBlocked = 125

// Errno returns the FxA API errno carried by err, or 0.
func Errno(err error) int {
	var apiErr *fxaAPIError
	if errors.As(err, &apiErr) {
		return apiErr.Errno
	}
	return 0
}

// HTTPStatus returns the status carried by an FxA API error, or 0.
func HTTPStatus(err error) int {
	var apiErr *fxaAPIError
	if errors.As(err, &apiErr) {
		return apiErr.Status
	}
	return 0
}

// Message returns the human-readable FxA error message carried by err,
// falling back to the error text.
func Message(err error) string {
	var apiErr *fxaAPIError
	if errors.As(err, &apiErr) {
		var body struct {
			Message string `json:"message"`
		}
		if json.Unmarshal([]byte(apiErr.Body), &body) == nil && body.Message != "" {
			return body.Message
		}
	}
	if err == nil {
		return ""
	}
	return err.Error()
}

// SignedInEmail is the email for the rest of a sign-in begun with typed:
// the account's own spelling when FxA corrected its letter case, whether
// the sign-in then succeeded or failed for another reason (such as a block
// that wants an unblock code); else typed.
func SignedInEmail(typed string, resp *LoginResponse, err error) string {
	if resp != nil && resp.Email != "" {
		return resp.Email
	}
	var caseErr *emailCaseError
	if errors.As(err, &caseErr) {
		return caseErr.email
	}
	return typed
}

// LoginWithUnblockCode repeats a blocked sign-in with the unblock code that
// SendUnblockCode had emailed.
func LoginWithUnblockCode(ctx context.Context, email, password, unblockCode string) (*LoginResponse, error) {
	return fxaLogin(ctx, email, password, strings.ToUpper(NormalizeCode(unblockCode)))
}

// SendUnblockCode asks FxA to email an unblock code for a blocked sign-in.
func SendUnblockCode(ctx context.Context, email string) error {
	body, _ := json.Marshal(map[string]string{"email": email})
	target := fxaAuthServer + "/account/login/send_unblock_code"
	resp, err := fxaDo(ctx, func() (*http.Request, error) {
		req, err := http.NewRequestWithContext(ctx, http.MethodPost, target, strings.NewReader(string(body)))
		if err != nil {
			return nil, err
		}
		req.Header.Set("Content-Type", "application/json")
		controlplane.ApplyFirefoxHeaders(req)
		return req, nil
	})
	if err != nil {
		return fmt.Errorf("unblock code request: %w", err)
	}
	defer resp.Body.Close()
	data, _ := io.ReadAll(io.LimitReader(resp.Body, 64*1024))
	if resp.StatusCode != http.StatusOK {
		return newFxaAPIError(resp.StatusCode, data)
	}
	return nil
}

// ErrTOTPRejected reports an explicit rejection of the authenticator code.
var ErrTOTPRejected = errors.New("the authenticator code was not accepted")

// VerifyTOTP verifies an unverified session with a code from the account's
// authenticator app (verification method "totp-2fa").
func VerifyTOTP(ctx context.Context, sessionToken, code string) error {
	hawkID, hawkKey, err := deriveHawkCredentials(sessionToken, "sessionToken")
	if err != nil {
		return fmt.Errorf("deriving hawk credentials: %w", err)
	}
	body, _ := json.Marshal(map[string]string{"code": NormalizeCode(code)})
	target := fxaAuthServer + "/session/verify/totp"
	resp, err := fxaDo(ctx, func() (*http.Request, error) {
		authHeader, err := hawkHeader(http.MethodPost, target, hawkID, hawkKey, string(body))
		if err != nil {
			return nil, err
		}
		req, err := http.NewRequestWithContext(ctx, http.MethodPost, target, strings.NewReader(string(body)))
		if err != nil {
			return nil, err
		}
		req.Header.Set("Content-Type", "application/json")
		req.Header.Set("Authorization", authHeader)
		controlplane.ApplyFirefoxHeaders(req)
		return req, nil
	})
	if err != nil {
		return fmt.Errorf("TOTP verification request: %w", err)
	}
	defer resp.Body.Close()
	data, err := io.ReadAll(io.LimitReader(resp.Body, 64*1024))
	if resp.StatusCode != http.StatusOK {
		return newFxaAPIError(resp.StatusCode, data)
	}
	if err != nil {
		return fmt.Errorf("reading TOTP verification response: %w", err)
	}
	var result struct {
		Success *bool `json:"success"`
	}
	if err := json.Unmarshal(data, &result); err != nil {
		return fmt.Errorf("parsing TOTP verification response: %w", err)
	}
	if result.Success == nil {
		return errors.New("TOTP verification response is missing success")
	}
	if !*result.Success {
		return ErrTOTPRejected
	}
	return nil
}

// CaptchaSolver shows a Fastly CAPTCHA image (a data: URL) to a person and
// returns the characters they read. It is called while an FxA request is in
// progress, so it should return within a few minutes.
type CaptchaSolver func(ctx context.Context, imageDataURL string) (string, error)

type captchaSolverKey struct{}

// WithCaptchaSolver lets FxA calls made with the returned context answer
// image CAPTCHAs, which the challenge solver cannot answer by itself.
func WithCaptchaSolver(ctx context.Context, solver CaptchaSolver) context.Context {
	return context.WithValue(ctx, captchaSolverKey{}, solver)
}

func captchaSolverFrom(ctx context.Context) CaptchaSolver {
	solver, _ := ctx.Value(captchaSolverKey{}).(CaptchaSolver)
	return solver
}
