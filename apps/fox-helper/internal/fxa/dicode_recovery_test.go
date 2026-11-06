package fxa

import (
	"context"
	"dicodeping/fox/internal/controlplane"
	"io"
	"net/http"
	"net/url"
	"strings"
	"testing"
)

func TestRefreshRetriesOAuthWithSolvedChallengeCookie(t *testing.T) {
	const cookie = "dicode-recovery-fixture"
	previous := controlplane.Transport()
	t.Cleanup(func() {
		controlplane.SetTransport(previous)
		for _, target := range []string{fxaAuthServer + "/", fxaSiteURL, fxaOAuthTokenURL} {
			u, _ := url.Parse(target)
			controlplane.SetCookies(u, []*http.Cookie{{Name: cookie, MaxAge: -1, Path: "/"}})
		}
	})
	alternate, solves := 0, 0
	controlplane.SetTransport(roundTripFunc(func(r *http.Request) (*http.Response, error) {
		response := func(status int, body string) *http.Response {
			return &http.Response{StatusCode: status, Header: make(http.Header), Body: io.NopCloser(strings.NewReader(body)), Request: r}
		}
		switch r.URL.Path {
		case "/v1/oauth/token":
			return response(406, ""), nil
		case "/v1/token":
			alternate++
			if _, err := r.Cookie(cookie); err == nil {
				return response(200, `{"access_token":"renewed","expires_in":3600}`), nil
			}
			return response(406, ""), nil
		case "/":
			if _, err := r.Cookie(cookie); err == nil {
				return response(200, "normal page"), nil
			}
			return response(200, `Client Challenge <script src="/_fs-ch-fixture/script.js"></script>`), nil
		case "/_fs-ch-fixture/script.js":
			return response(200, `init([{"ty":"clientmetrics","data":{}}], "fixture-token", "/_fs-ch-fixture")`), nil
		case "/_fs-ch-fixture/fst-post-back":
			solves++
			resp := response(200, `{"status":"success"}`)
			resp.Header.Set("Set-Cookie", cookie+"=accepted; Path=/; Secure")
			return resp, nil
		default:
			t.Fatalf("unexpected request %s", r.URL)
			return nil, nil
		}
	}))
	token, err := RefreshToken(context.Background(), "stored-refresh")
	if err != nil {
		t.Fatal(err)
	}
	if token.AccessToken != "renewed" || token.RefreshToken != "stored-refresh" || alternate != 2 || solves != 1 {
		t.Fatalf("recovery failed: alternate=%d solves=%d", alternate, solves)
	}
}
