package controlplane

import (
	"context"
	"io"
	"net/http"
	"strings"
	"testing"
)

type remoteRoundTrip func(*http.Request) (*http.Response, error)

func (f remoteRoundTrip) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }
func remoteFixture(t *testing.T, f remoteRoundTrip) {
	t.Helper()
	previous := activeRemote.Load()
	transport := client.Transport
	c, e := parseRemote(defaultConfig)
	if e != nil {
		t.Fatal(e)
	}
	activeRemote.Store(c)
	client.Transport = f
	t.Cleanup(func() { activeRemote.Store(previous); client.Transport = transport })
}
func TestRemoteRetriesBlockedControlPlaneWithReplayableBody(t *testing.T) {
	calls := 0
	remoteFixture(t, func(r *http.Request) (*http.Response, error) {
		calls++
		body, _ := io.ReadAll(r.Body)
		if string(body) != "grant=private" {
			t.Fatal("body lost")
		}
		status := 406
		if calls == 2 {
			status = 200
			if r.URL.Query().Get("url") != "https://api.accounts.firefox.com/v1/oauth/token" {
				t.Fatal("wrong relay target")
			}
			if r.Header.Get("Authorization") != "secret" {
				t.Fatal("authorization lost")
			}
		}
		return &http.Response{StatusCode: status, Body: io.NopCloser(strings.NewReader("{}")), Header: make(http.Header), Request: r}, nil
	})
	req, _ := http.NewRequest("POST", "https://api.accounts.firefox.com/v1/oauth/token", strings.NewReader("grant=private"))
	req.Header.Set("Authorization", "secret")
	resp, e := remoteDo(req)
	if e != nil {
		t.Fatal(e)
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 || calls != 2 {
		t.Fatalf("status=%d calls=%d", resp.StatusCode, calls)
	}
}
func TestRemoteDoesNotReplayAcceptedOrAuthenticationFailure(t *testing.T) {
	for _, status := range []int{200, 401, 429} {
		t.Run(http.StatusText(status), func(t *testing.T) {
			calls := 0
			remoteFixture(t, func(r *http.Request) (*http.Response, error) {
				calls++
				return &http.Response{StatusCode: status, Body: io.NopCloser(strings.NewReader("")), Header: make(http.Header), Request: r}, nil
			})
			req, _ := http.NewRequest("GET", "https://vpn.mozilla.org/api/v1/fpn/token", nil)
			resp, e := remoteDo(req)
			if e != nil {
				t.Fatal(e)
			}
			resp.Body.Close()
			if calls != 1 {
				t.Fatal("accepted request replayed")
			}
		})
	}
}
func TestRemoteCancellationNeverStartsRelay(t *testing.T) {
	calls := 0
	remoteFixture(t, func(r *http.Request) (*http.Response, error) { calls++; return nil, context.Canceled })
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	req, _ := http.NewRequestWithContext(ctx, "GET", "https://vpn.mozilla.org/api/v1/fpn/token", nil)
	_, e := remoteDo(req)
	if e != context.Canceled || calls > 1 {
		t.Fatal("canceled request retried")
	}
}
func TestRemoteRejectsUnexpectedRelayAndMalformedCache(t *testing.T) {
	for _, data := range []string{`{}`, `{"version":10,"relayers":{"bad":"http://relayer.foxyvpn.workers.dev"}}`, `{"version":10,"relayers":{"bad":"https://attacker.example"}}`} {
		if _, e := parseRemote([]byte(data)); e == nil {
			t.Fatal("invalid config accepted")
		}
	}
}
