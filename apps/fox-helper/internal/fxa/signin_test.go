package fxa

import (
	"context"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/url"
	"strings"
	"testing"

	"dicodeping/fox/internal/controlplane"
)

type roundTripFunc func(*http.Request) (*http.Response, error)

func (f roundTripFunc) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }

func useFxaFixture(t *testing.T, handler func(r *http.Request, body map[string]any) (int, string)) {
	t.Helper()
	previous := controlplane.Transport()
	t.Cleanup(func() { controlplane.SetTransport(previous) })
	controlplane.SetTransport(roundTripFunc(func(r *http.Request) (*http.Response, error) {
		var body map[string]any
		if r.Body != nil {
			_ = json.NewDecoder(r.Body).Decode(&body)
		}
		status, text := handler(r, body)
		return &http.Response{StatusCode: status, Header: make(http.Header), Body: io.NopCloser(strings.NewReader(text)), Request: r}, nil
	}))
}

func TestOAuthTokenTriesHTTP2BeforeAuthorizationCode(t *testing.T) {
	const tokenURL = fxaAuthServer + "/oauth/token"
	const tokenJSON = `{"access_token":"fixture-access","refresh_token":"fixture-refresh"}`
	for _, tc := range []struct {
		name       string
		status     int
		wantGrants string
	}{
		{"HTTP/2 succeeds", http.StatusOK, "original HTTP/2"},
		{"HTTP/2 is refused", http.StatusNotAcceptable, "original HTTP/2 authorization exchange"},
		{"HTTP/2 cannot connect", 0, "original HTTP/2 authorization exchange"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			checkGrant := func(r *http.Request, body map[string]any) {
				t.Helper()
				if r.URL.String() != tokenURL || r.Method != http.MethodPost ||
					!strings.HasPrefix(r.Header.Get("Authorization"), "Hawk ") || body["grant_type"] != "fxa-credentials" ||
					body["client_id"] != firefoxClientID || body["scope"] != oauthScope || body["access_type"] != "offline" {
					t.Fatal("expected the session-authenticated offline VPN grant")
				}
			}
			var grants []string
			useFxaFixture(t, func(r *http.Request, body map[string]any) (int, string) {
				switch r.URL.String() {
				case tokenURL:
					grants = append(grants, "original")
					checkGrant(r, body)
					return http.StatusNotAcceptable, ""
				case fxaAuthServer + "/oauth/authorization":
					grants = append(grants, "authorization")
					state, _ := body["state"].(string)
					return http.StatusOK, `{"code":"fixture-code","state":"` + state + `"}`
				case fxaOAuthTokenURL:
					grants = append(grants, "exchange")
					if body["grant_type"] != "authorization_code" || body["code"] != "fixture-code" {
						t.Fatal("expected authorization code redemption")
					}
					return http.StatusOK, tokenJSON
				default:
					t.Fatalf("unexpected OAuth target %s", r.URL)
					return 0, ""
				}
			})
			sendHTTP2 := func(r *http.Request) (*http.Response, error) {
				grants = append(grants, "HTTP/2")
				defer r.Body.Close()
				var body map[string]any
				if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
					t.Fatalf("cannot read the retried grant: %v", err)
				}
				checkGrant(r, body)
				if tc.status == 0 {
					return nil, errors.New("fixture connection failure")
				}
				return &http.Response{StatusCode: tc.status, Body: io.NopCloser(strings.NewReader(tokenJSON)), Request: r}, nil
			}
			token, err := fxaOAuthToken(context.Background(), strings.Repeat("00", 32), sendHTTP2)
			if err != nil || token.AccessToken != "fixture-access" || token.RefreshToken != "fixture-refresh" {
				t.Fatalf("token exchange failed: %v", err)
			}
			if got := strings.Join(grants, " "); got != tc.wantGrants {
				t.Fatalf("tried %q, want %q", got, tc.wantGrants)
			}
		})
	}
}

func TestOAuthTokenUsesAuthorizationCodeAfter406(t *testing.T) {
	for _, mismatch := range []bool{false, true} {
		name := "matching state"
		if mismatch {
			name = "mismatched state"
		}
		t.Run(name, func(t *testing.T) {
			var challenge string
			var calls int
			useFxaFixture(t, func(r *http.Request, body map[string]any) (int, string) {
				calls++
				if r.Method != http.MethodPost || body["client_id"] != firefoxClientID {
					t.Fatalf("unexpected OAuth request to %s", r.URL)
				}
				switch r.URL.String() {
				case fxaAuthServer + "/oauth/token":
					if calls != 1 || body["grant_type"] != "fxa-credentials" || !strings.HasPrefix(r.Header.Get("Authorization"), "Hawk ") {
						t.Fatal("expected the original session exchange first")
					}
					return http.StatusNotAcceptable, ""
				case fxaAuthServer + "/oauth/authorization":
					state, _ := body["state"].(string)
					challenge, _ = body["code_challenge"].(string)
					if calls != 2 || state == "" || len(challenge) != 43 || body["code_challenge_method"] != "S256" ||
						body["scope"] != oauthScope || body["access_type"] != "offline" || body["response_type"] != "code" ||
						!strings.HasPrefix(r.Header.Get("Authorization"), "Hawk ") {
						t.Fatal("expected session-authenticated offline authorization with PKCE")
					}
					if mismatch {
						state += "x"
					}
					return http.StatusOK, `{"code":"fixture-code","state":"` + state + `"}`
				case fxaOAuthTokenURL:
					verifier, _ := body["code_verifier"].(string)
					digest := sha256.Sum256([]byte(verifier))
					if mismatch || calls != 3 || body["grant_type"] != "authorization_code" || body["code"] != "fixture-code" ||
						r.Header.Get("Authorization") != "" || len(verifier) != 43 || base64.RawURLEncoding.EncodeToString(digest[:]) != challenge {
						t.Fatal("expected the issued code with its matching verifier and no session credential")
					}
					return http.StatusOK, `{"access_token":"fixture-access","refresh_token":"fixture-refresh"}`
				default:
					t.Fatalf("unexpected OAuth target %s", r.URL)
					return 0, ""
				}
			})
			token, err := OAuthToken(context.Background(), strings.Repeat("00", 32))
			if mismatch {
				if err == nil || calls != 2 {
					t.Fatalf("wrong state: got %d requests and error %v", calls, err)
				}
			} else if err != nil || token.AccessToken != "fixture-access" || token.RefreshToken != "fixture-refresh" || calls != 3 {
				t.Fatalf("sign-in via authorization code failed: %v (calls=%d)", err, calls)
			}
		})
	}
}

func TestOAuthTokenSharesChallengeRecoveryBetweenGrants(t *testing.T) {
	const cookieName = "oauth-retry-fixture"
	const prefix = "/_fs-ch-oauthFixture"
	const tokenPath = "/v1/oauth/token"
	const authorizationPath = "/v1/oauth/authorization"
	const tokenJSON = `{"access_token":"fixture-access","refresh_token":"fixture-refresh"}`
	for _, tc := range []struct {
		name          string
		primaryStatus int
		wantRequests  []string
	}{
		{"original grant succeeds after challenge", http.StatusOK, []string{tokenPath, authorizationPath, tokenPath}},
		{"alternate grant succeeds after challenge", http.StatusNotAcceptable, []string{tokenPath, authorizationPath, tokenPath, authorizationPath, "/v1/token"}},
	} {
		t.Run(tc.name, func(t *testing.T) {
			previous := controlplane.Transport()
			t.Cleanup(func() {
				controlplane.SetTransport(previous)
				for _, target := range []string{fxaAuthServer + "/", fxaSiteURL} {
					u, _ := url.Parse(target)
					controlplane.SetCookies(u, []*http.Cookie{{Name: cookieName, MaxAge: -1}})
				}
			})

			var requests []string
			var solves int
			controlplane.SetTransport(roundTripFunc(func(r *http.Request) (*http.Response, error) {
				response := func(status int, body string) *http.Response {
					return &http.Response{StatusCode: status, Header: make(http.Header), Body: io.NopCloser(strings.NewReader(body)), Request: r}
				}
				switch r.URL.Path {
				case tokenPath, authorizationPath, "/v1/token":
					requests = append(requests, r.URL.Path)
					if len(requests) > len(tc.wantRequests) || r.URL.Path != tc.wantRequests[len(requests)-1] {
						t.Fatalf("unexpected grant requests %v, want %v", requests, tc.wantRequests)
					}
					if len(requests) <= 2 {
						return response(http.StatusNotAcceptable, ""), nil
					}
					if r.URL.Path == "/v1/token" {
						return response(http.StatusOK, tokenJSON), nil
					}
					if _, err := r.Cookie(cookieName); err != nil {
						t.Fatalf("grant retried without the challenge cookie: %s", r.URL.Path)
					}
					if r.URL.Path == tokenPath {
						return response(tc.primaryStatus, tokenJSON), nil
					}
					var body struct{ State string }
					if err := json.NewDecoder(r.Body).Decode(&body); err != nil || body.State == "" {
						t.Fatal("expected alternate authorization with a state")
					}
					return response(http.StatusOK, `{"code":"fixture-code","state":"`+body.State+`"}`), nil
				case "/":
					if _, err := r.Cookie(cookieName); err == nil {
						return response(http.StatusOK, "normal page"), nil
					}
					return response(http.StatusOK, `Client Challenge <script src="`+prefix+`/script.js"></script>`), nil
				case prefix + "/script.js":
					return response(http.StatusOK, `init([{"ty":"clientmetrics","data":{}}], "fixture-token", "`+prefix+`")`), nil
				case prefix + "/fst-post-back":
					solves++
					resp := response(http.StatusOK, `{"status":"success"}`)
					resp.Header.Set("Set-Cookie", cookieName+"=cleared; Path=/; Secure")
					return resp, nil
				default:
					t.Fatalf("unexpected request to %s", r.URL.Path)
					return nil, nil
				}
			}))

			token, err := OAuthToken(context.Background(), strings.Repeat("00", 32))
			if err != nil || token.AccessToken != "fixture-access" || token.RefreshToken != "fixture-refresh" {
				t.Fatalf("token exchange failed after alternate 406: %v", err)
			}
			if len(requests) != len(tc.wantRequests) || solves != 1 {
				t.Fatalf("got grant requests %v and %d solves, want %v and one solve", requests, solves, tc.wantRequests)
			}
		})
	}
}

func TestRefreshTokenFallsBackToOAuthEndpointOn406(t *testing.T) {
	const storedRefresh = "synthetic-refresh"
	for _, tc := range []struct {
		name            string
		primaryStatus   int
		alternateStatus int
		body            string
		wantReauth      bool
	}{
		{"primary succeeds", 200, 0, `{"access_token":"fresh"}`, false},
		{"primary rejects token", 400, 0, `{"errno":110}`, true},
		{"alternate succeeds", 406, 200, `{"access_token":"fresh"}`, false},
		{"alternate rejects token", 406, 400, `{"errno":108}`, true},
		{"alternate refuses request", 406, 403, ``, false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			calls := 0
			useFxaFixture(t, func(r *http.Request, body map[string]any) (int, string) {
				calls++
				if r.Method != http.MethodPost || r.Header.Get("Authorization") != "" ||
					body["grant_type"] != "refresh_token" || body["refresh_token"] != storedRefresh ||
					body["client_id"] != firefoxClientID || body["scope"] != oauthScope {
					t.Fatalf("unexpected refresh request to %s", r.URL)
				}
				switch {
				case calls == 1 && r.URL.String() == fxaAuthServer+"/oauth/token":
					if tc.primaryStatus == http.StatusNotAcceptable {
						return tc.primaryStatus, ""
					}
					return tc.primaryStatus, tc.body
				case calls == 2 && tc.alternateStatus != 0 && r.URL.String() == fxaOAuthTokenURL:
					return tc.alternateStatus, tc.body
				default:
					t.Fatalf("unexpected call %d to %s", calls, r.URL)
					return 0, ""
				}
			})
			token, err := RefreshToken(context.Background(), storedRefresh)
			if tc.primaryStatus == http.StatusOK || tc.alternateStatus == http.StatusOK {
				if err != nil || token.AccessToken != "fresh" || token.RefreshToken != storedRefresh {
					t.Fatalf("refresh failed or lost the saved token: %v", err)
				}
			} else if err == nil || errors.Is(err, ErrReauthRequired) != tc.wantReauth {
				t.Fatalf("refresh error %v, want reauthentication = %t", err, tc.wantReauth)
			}
			if tc.alternateStatus != 0 && calls != 2 {
				t.Fatalf("got %d requests, want a primary request and one fallback", calls)
			}
		})
	}
}

func TestErrnoAndMessageReadFxaErrors(t *testing.T) {
	err := error(newFxaAPIError(400, []byte(`{"errno":125,"message":"Request blocked"}`)))
	if Errno(err) != ErrnoRequestBlocked || Message(err) != "Request blocked" {
		t.Fatalf("unexpected errno/message: %d %q", Errno(err), Message(err))
	}
	if Errno(errors.New("plain")) != 0 || Message(errors.New("plain")) != "plain" {
		t.Fatal("plain errors must fall back to their text")
	}
}

func TestLoginWithUnblockCodeSendsCode(t *testing.T) {
	useFxaFixture(t, func(r *http.Request, body map[string]any) (int, string) {
		if r.URL.Path != "/v1/account/login" || body["unblockCode"] != "ABC123" || body["email"] != "user@example.com" {
			return 500, "unexpected request"
		}
		return 200, `{"sessionToken":"00","uid":"u","verified":true}`
	})
	resp, err := LoginWithUnblockCode(context.Background(), "user@example.com", "secret", " abc123 ")
	if err != nil || !resp.Verified {
		t.Fatalf("expected a verified login, got %+v %v", resp, err)
	}
}

// An email typed in another letter case than the account's: FxA refuses it
// with the account's own spelling (errno 120), and the sign-in is repeated
// once with that spelling, its own password hash, and the typed email as
// originalLoginEmail, as Firefox does.
func TestLoginCorrectsTheEmailCase(t *testing.T) {
	const stored, typed = "Asra@example.com", "asra@example.com"
	wantAuthPW, err := deriveAuthPW(stored, "secret")
	if err != nil {
		t.Fatal(err)
	}
	var emails []any
	useFxaFixture(t, func(r *http.Request, body map[string]any) (int, string) {
		emails = append(emails, body["email"])
		if body["email"] != stored {
			return 400, `{"code":400,"errno":120,"message":"Incorrect email case","email":"` + stored + `"}`
		}
		if body["originalLoginEmail"] != typed || body["authPW"] != hex.EncodeToString(wantAuthPW) {
			return 500, "unexpected request"
		}
		return 200, `{"sessionToken":"00","uid":"u","verified":true}`
	})
	resp, err := Login(context.Background(), typed, "secret")
	if err != nil || resp.Email != stored || SignedInEmail(typed, resp, err) != stored {
		t.Fatalf("login %+v %v; want it signed in as %s", resp, err, stored)
	}
	if len(emails) != 2 {
		t.Fatalf("emails sent %v; want the typed one, then the account's", emails)
	}

	// The corrected sign-in is blocked: the error keeps the account's
	// spelling, for the unblock code and the next attempt.
	useFxaFixture(t, func(r *http.Request, body map[string]any) (int, string) {
		if body["email"] != stored {
			return 400, `{"errno":120,"email":"` + stored + `"}`
		}
		return 400, `{"errno":125,"message":"Request blocked"}`
	})
	resp, err = Login(context.Background(), typed, "secret")
	if Errno(err) != ErrnoRequestBlocked || SignedInEmail(typed, resp, err) != stored {
		t.Fatalf("blocked login: %v, email %q", err, SignedInEmail(typed, resp, err))
	}

	// A wrong password in the right case is an ordinary failure, not
	// repeated.
	calls := 0
	useFxaFixture(t, func(r *http.Request, body map[string]any) (int, string) {
		calls++
		return 400, `{"errno":103,"message":"Incorrect password","email":"` + stored + `"}`
	})
	_, err = Login(context.Background(), stored, "wrong")
	if Errno(err) != 103 || calls != 1 || SignedInEmail(stored, nil, err) != stored {
		t.Fatalf("wrong password: %v after %d calls", err, calls)
	}
}

func TestVerifyTOTPReportsRejectedCode(t *testing.T) {
	accept := false
	useFxaFixture(t, func(r *http.Request, body map[string]any) (int, string) {
		if r.URL.Path != "/v1/session/verify/totp" || !strings.HasPrefix(r.Header.Get("Authorization"), "Hawk ") || body["code"] != "123456" {
			return 500, "unexpected request"
		}
		if accept {
			return 200, `{"success":true}`
		}
		return 200, `{"success":false}`
	})
	session := strings.Repeat("ab", 32)
	if err := VerifyTOTP(context.Background(), session, "123456"); err == nil {
		t.Fatal("expected a rejected code to fail")
	}
	accept = true
	if err := VerifyTOTP(context.Background(), session, " 123456 "); err != nil {
		t.Fatalf("expected success, got %v", err)
	}
}

func TestAnswerChallengeAsksCaptchaSolver(t *testing.T) {
	ch := fastlyChallenge{Ty: "captcha", Data: json.RawMessage(`{"image_b64":"data:image/png;base64,AAAA"}`)}
	if _, err := answerChallenge(context.Background(), nil, "", "", ch); err == nil {
		t.Fatal("expected an error without a CAPTCHA solver")
	}
	var shown string
	ctx := WithCaptchaSolver(context.Background(), func(_ context.Context, image string) (string, error) {
		shown = image
		return " x7Kp2 ", nil
	})
	answer, err := answerChallenge(ctx, nil, "", "", ch)
	if err != nil {
		t.Fatal(err)
	}
	got := answer.(map[string]interface{})
	if got["ty"] != "captcha" || got["answer"] != "x7Kp2" || shown != "data:image/png;base64,AAAA" {
		t.Fatalf("unexpected CAPTCHA answer %v (shown %q)", got, shown)
	}
}
