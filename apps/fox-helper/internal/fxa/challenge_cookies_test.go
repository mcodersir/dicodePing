package fxa

import (
	"net/http"
	"net/http/cookiejar"
	"net/url"
	"testing"

	"dicodeping/fox/internal/controlplane"
)

func TestChallengeCookiesReachAlternateOAuthWithoutOtherHosts(t *testing.T) {
	const cookieName = "challenge-origins-fixture"
	solverJar, err := cookiejar.New(nil)
	if err != nil {
		t.Fatal(err)
	}
	pageURL, _ := url.Parse(fxaSiteURL)
	solverJar.SetCookies(pageURL, []*http.Cookie{{
		Name: cookieName, Value: "synthetic-clearance", Domain: "firefox.com", Path: "/", Secure: true,
	}})
	t.Cleanup(func() {
		for _, target := range []string{fxaAuthServer + "/", "https://api.accounts.firefox.com/", "https://oauth.accounts.firefox.com/", fxaSiteURL} {
			u, _ := url.Parse(target)
			controlplane.SetCookies(u, []*http.Cookie{{Name: cookieName, MaxAge: -1}})
		}
	})
	if err := installChallengeCookies(solverJar, fxaSiteURL); err != nil {
		t.Fatal(err)
	}

	cases := map[string]bool{
		fxaAuthServer + "/oauth/token":             true,
		"https://api.accounts.firefox.com/":        true,
		fxaOAuthTokenURL:                           true,
		"https://oauth.accounts.firefox.com/":      true,
		fxaSiteURL:                                 true,
		"https://vpn.mozilla.org/api/v1/fpn/token": false,
		"https://notfirefox.com/":                  false,
	}
	useFxaFixture(t, func(req *http.Request, _ map[string]any) (int, string) {
		wantCookie, ok := cases[req.URL.String()]
		if !ok {
			t.Fatalf("unexpected fixture target %s", req.URL)
		}
		cookie, err := req.Cookie(cookieName)
		if wantCookie && (err != nil || cookie.Value != "synthetic-clearance") {
			t.Errorf("solved challenge cookie missing at %s", req.URL)
		} else if !wantCookie && err == nil {
			t.Errorf("solved challenge cookie sent outside FxA at %s", req.URL)
		}
		return http.StatusNoContent, ""
	})
	for target := range cases {
		req, _ := http.NewRequest(http.MethodGet, target, nil)
		response, err := controlplane.Do(req)
		if err != nil {
			t.Fatal(err)
		}
		response.Body.Close()
	}
}
