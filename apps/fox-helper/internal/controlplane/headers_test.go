package controlplane

import (
	"net/http"
	"strings"
	"testing"
)

func TestFirefoxPlatform(t *testing.T) {
	for _, tc := range []struct{ goos, goarch, want string }{
		{"windows", "amd64", "Windows NT 10.0; Win64; x64"},
		{"darwin", "arm64", "Macintosh; Intel Mac OS X 10.15"},
		{"linux", "amd64", "X11; Linux x86_64"},
		{"linux", "arm64", "X11; Linux aarch64"},
		{"android", "arm64", "Windows NT 10.0; Win64; x64"},
	} {
		if got := firefoxPlatform(tc.goos, tc.goarch); got != tc.want {
			t.Errorf("%s/%s: got %q, want %q", tc.goos, tc.goarch, got, tc.want)
		}
	}
}

// The User-Agent names the Firefox release product details gave, and keeps
// the last good one when an answer is not a version.
func TestFirefoxUserAgentFollowsTheRelease(t *testing.T) {
	t.Cleanup(func() { firefoxMajor.Store(defaultFirefoxMajor) })
	SetFirefoxVersion("163.0.2")
	ua := FirefoxUserAgent()
	if !strings.HasPrefix(ua, "Mozilla/5.0 (") || !strings.HasSuffix(ua, "; rv:163.0) Gecko/20100101 Firefox/163.0") {
		t.Fatalf("user agent %q", ua)
	}
	SetFirefoxVersion("")
	SetFirefoxVersion("nightly")
	if !strings.HasSuffix(FirefoxUserAgent(), "Firefox/163.0") {
		t.Fatalf("a bad version replaced the release: %q", FirefoxUserAgent())
	}

	req, _ := http.NewRequest(http.MethodGet, "https://vpn.mozilla.org/api/v1/fpn/token", nil)
	ApplyFirefoxHeaders(req)
	if req.Header.Get("User-Agent") != ua || req.Header.Get("Accept") != "*/*" {
		t.Fatalf("headers %v", req.Header)
	}
	if got := req.Header.Get("Accept-Encoding"); got != "identity" {
		t.Fatalf("Accept-Encoding = %q, want identity", got)
	}
}

func TestFirefoxHeadersIncludeFetchMetadata(t *testing.T) {
	for _, target := range []string{"https://api.accounts.firefox.com/v1/oauth/token", "https://oauth.accounts.firefox.com/v1/token", "https://firefox.settings.services.mozilla.com/v1/"} {
		req, _ := http.NewRequest("POST", target, nil)
		ApplyFirefoxHeaders(req)
		if req.Header.Get("Sec-Fetch-Dest") != "empty" || req.Header.Get("Sec-Fetch-Mode") != "cors" || req.Header.Get("Sec-Fetch-Site") != "same-site" || req.Header.Get("Origin") != "https://accounts.firefox.com" || req.Header.Get("Referer") != "https://accounts.firefox.com/" {
			t.Fatalf("incomplete browser metadata for %s", target)
		}
	}
	req, _ := http.NewRequest("GET", "https://evilfirefox.com/", nil)
	ApplyFirefoxHeaders(req)
	if req.Header.Get("Origin") != "" || req.Header.Get("Referer") != "" {
		t.Fatal("Mozilla origin metadata leaked to an unrelated domain")
	}
}
