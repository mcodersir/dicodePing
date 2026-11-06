package controlplane

import (
	"io"
	"net/http"
	"net/http/httptest"
	"testing"
)

// A proxy in the environment (another program's, not running) is not
// used: the requests go straight to their server.
func TestRequestsIgnoreTheEnvironmentsProxy(t *testing.T) {
	t.Setenv("HTTP_PROXY", "http://127.0.0.1:1")
	t.Setenv("HTTPS_PROXY", "http://127.0.0.1:1")
	t.Setenv("NO_PROXY", "")
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_, _ = io.WriteString(w, "ok")
	}))
	defer srv.Close()
	if defaultTransport.Proxy != nil {
		t.Fatal("the default transport has a proxy")
	}
	// Go never proxies loopback, so a request to the test server says
	// nothing; the transport's own Proxy decides for other hosts.
	req, _ := http.NewRequest(http.MethodGet, "https://vpn.mozilla.org/", nil)
	if u, err := http.ProxyFromEnvironment(req); err != nil || u == nil {
		t.Fatalf("the environment's proxy is set for the check: %v %v", u, err)
	}
	resp, err := (&http.Client{Transport: defaultTransport}).Get(srv.URL)
	if err != nil {
		t.Fatal(err)
	}
	resp.Body.Close()
}
