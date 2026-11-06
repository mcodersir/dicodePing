package serverlist

import (
	"context"
	"io"
	"net/http"
	"strings"
	"testing"

	"dicodeping/fox/internal/controlplane"
)

type versionRoundTripper func(*http.Request) (*http.Response, error)

func (f versionRoundTripper) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }

func serveVersions(t *testing.T, status int, body string) {
	t.Helper()
	previous := controlplane.Transport()
	t.Cleanup(func() { controlplane.SetTransport(previous) })
	controlplane.SetTransport(versionRoundTripper(func(r *http.Request) (*http.Response, error) {
		if r.URL.String() != productDetailsURL {
			t.Errorf("unexpected request %s", r.URL)
		}
		return &http.Response{StatusCode: status, Header: make(http.Header), Body: io.NopCloser(strings.NewReader(body)), Request: r}, nil
	}))
}

func TestLatestFirefoxVersionPrefersNightly(t *testing.T) {
	serveVersions(t, 200, `{"FIREFOX_NIGHTLY":"161.0a1","LATEST_FIREFOX_VERSION":"158.0"}`)
	if v, err := LatestFirefoxVersion(context.Background()); err != nil || v != "161.0a1" {
		t.Fatalf("got %q %v", v, err)
	}
	serveVersions(t, 200, `{"FIREFOX_NIGHTLY":"","LATEST_FIREFOX_VERSION":"158.0.1"}`)
	if v, err := LatestFirefoxVersion(context.Background()); err != nil || v != "158.0.1" {
		t.Fatalf("release fallback: %q %v", v, err)
	}
	serveVersions(t, 503, `busy`)
	if _, err := LatestFirefoxVersion(context.Background()); err == nil {
		t.Fatal("an HTTP error must fail")
	}
}
