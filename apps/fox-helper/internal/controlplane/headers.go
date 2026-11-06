package controlplane

import (
	"fmt"
	"net/http"
	"runtime"
	"strings"
	"sync/atomic"
)

// defaultFirefoxMajor is the Firefox release when this was written; the
// current one replaces it once Mozilla's product details answer
// (SetFirefoxVersion), so the User-Agent never falls far behind.
const defaultFirefoxMajor = "158"

var firefoxMajor atomic.Value // string

// SetFirefoxVersion makes FirefoxUserAgent name the Firefox release
// version ("158.0.1", product details' LATEST_FIREFOX_VERSION); anything
// that does not start with a number is ignored.
func SetFirefoxVersion(version string) {
	major, _, _ := strings.Cut(strings.TrimSpace(version), ".")
	if major == "" || strings.Trim(major, "0123456789") != "" {
		return
	}
	firefoxMajor.Store(major)
}

// FirefoxUserAgent is the User-Agent of desktop Firefox on this system,
// which Firefox's built-in VPN sends with every request it makes: to
// Guardian, Firefox Accounts, Remote Settings, and the proxy's CONNECT.
// The built-in VPN is a desktop feature, so Android gets the most common
// desktop's: Windows.
func FirefoxUserAgent() string {
	major, _ := firefoxMajor.Load().(string)
	if major == "" {
		major = defaultFirefoxMajor
	}
	return fmt.Sprintf("Mozilla/5.0 (%s; rv:%s.0) Gecko/20100101 Firefox/%s.0", firefoxPlatform(runtime.GOOS, runtime.GOARCH), major, major)
}

// firefoxPlatform is the system part of Firefox's User-Agent: Firefox
// reports Windows 11 as NT 10.0 and every Mac as Intel, 10.15.
func firefoxPlatform(goos, goarch string) string {
	switch goos {
	case "windows", "android":
		return "Windows NT 10.0; Win64; x64"
	case "darwin":
		return "Macintosh; Intel Mac OS X 10.15"
	}
	if goarch == "arm64" {
		return "X11; Linux aarch64"
	}
	return "X11; Linux x86_64"
}

// ApplyFirefoxHeaders sets the User-Agent and Accept headers Firefox sends
// with every control plane API request.
func ApplyFirefoxHeaders(req *http.Request) {
	req.Header.Set("User-Agent", FirefoxUserAgent())
	req.Header.Set("Accept", "*/*")
}
