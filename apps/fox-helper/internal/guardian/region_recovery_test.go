package guardian

import (
	"errors"
	"io"
	"net/http"
	"strings"
	"testing"

	"dicodeping/fox/internal/controlplane"
)

type regionRoundTrip func(*http.Request) (*http.Response, error)

func (f regionRoundTrip) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }

func regionResponse(r *http.Request, status int, body string) *http.Response {
	return &http.Response{
		StatusCode: status,
		Header:     make(http.Header),
		Body:       io.NopCloser(strings.NewReader(body)),
		Request:    r,
	}
}

func TestRegionRecoveryOnlyAfter451AndKeepsOriginalFailure(t *testing.T) {
	previous := controlplane.Transport()
	t.Cleanup(func() { controlplane.SetTransport(previous); SetRegionRecovery(nil) })
	var status, called int
	var paths []string
	controlplane.SetTransport(regionRoundTrip(func(r *http.Request) (*http.Response, error) {
		paths = append(paths, r.URL.Path)
		return regionResponse(r, status, `{"error":"unavailable_in_region"}`), nil
	}))
	SetRegionRecovery(func(*http.Request) (*http.Response, error) { called++; return nil, nil })
	for _, code := range []int{200, 401, 403, 406, 500, 451} {
		status = code
		paths = nil
		req, _ := http.NewRequest(http.MethodGet, "https://vpn.mozilla.org/api/v1/fpn/token", nil)
		resp, err := do(req)
		if err != nil || resp.StatusCode != code {
			t.Fatalf("response %d: %v", code, err)
		}
		body, err := io.ReadAll(resp.Body)
		resp.Body.Close()
		if err != nil || len(body) == 0 {
			t.Fatal("original response lost")
		}
		want := []string{"/api/v1/fpn/token"}
		if code == http.StatusUnavailableForLegalReasons {
			want = append(want, "//api/v1/fpn/token")
		}
		if strings.Join(paths, ",") != strings.Join(want, ",") {
			t.Fatalf("status %d: paths = %v, want %v", code, paths, want)
		}
	}
	if called != 1 {
		t.Fatalf("recovery called %d times", called)
	}
}

func TestDoubledPathRecoversBeforeTheRelay(t *testing.T) {
	previous := controlplane.Transport()
	t.Cleanup(func() { controlplane.SetTransport(previous); SetRegionRecovery(nil) })
	var paths []string
	controlplane.SetTransport(regionRoundTrip(func(r *http.Request) (*http.Response, error) {
		paths = append(paths, r.URL.Path)
		if r.URL.Path == "//api/v1/fpn/status" {
			return regionResponse(r, http.StatusOK, `{"subscribed":true,"uid":1}`), nil
		}
		return regionResponse(r, http.StatusUnavailableForLegalReasons, `{"error":"unavailable_in_region"}`), nil
	}))
	relayCalled := false
	SetRegionRecovery(func(r *http.Request) (*http.Response, error) {
		relayCalled = true
		return regionResponse(r, http.StatusOK, `{"subscribed":true,"uid":1}`), nil
	})

	info, err := FetchUserInfo(t.Context(), DefaultEndpoint, "fixture")
	if err != nil || !info.Subscribed {
		t.Fatalf("direct recovery was lost: %v", err)
	}
	if relayCalled {
		t.Fatal("relay recovery ran even though the doubled path succeeded")
	}
	want := []string{"/api/v1/fpn/status", "//api/v1/fpn/status"}
	if strings.Join(paths, ",") != strings.Join(want, ",") {
		t.Fatalf("paths = %v, want %v", paths, want)
	}
}

func TestDoubledPathFailureFallsBackToTheRelay(t *testing.T) {
	previous := controlplane.Transport()
	t.Cleanup(func() { controlplane.SetTransport(previous); SetRegionRecovery(nil) })
	controlplane.SetTransport(regionRoundTrip(func(r *http.Request) (*http.Response, error) {
		if strings.HasPrefix(r.URL.Path, "//") {
			return nil, errors.New("direct retry failed")
		}
		return regionResponse(r, http.StatusUnavailableForLegalReasons, `{"error":"unavailable_in_region"}`), nil
	}))
	relayCalled := false
	SetRegionRecovery(func(r *http.Request) (*http.Response, error) {
		relayCalled = true
		return regionResponse(r, http.StatusOK, `{"subscribed":true,"uid":1}`), nil
	})

	info, err := FetchUserInfo(t.Context(), DefaultEndpoint, "fixture")
	if err != nil || !info.Subscribed {
		t.Fatalf("relay fallback was lost: %v", err)
	}
	if !relayCalled {
		t.Fatal("relay recovery did not run after the direct retry failed")
	}
}

func TestDoubledPathRetryKeepsMethodHeadersAndQuery(t *testing.T) {
	previous := controlplane.Transport()
	t.Cleanup(func() { controlplane.SetTransport(previous); SetRegionRecovery(nil) })
	var retried *http.Request
	controlplane.SetTransport(regionRoundTrip(func(r *http.Request) (*http.Response, error) {
		if strings.HasPrefix(r.URL.Path, "//") {
			retried = r
			return regionResponse(r, http.StatusOK, `{"subscribed":true,"uid":1}`), nil
		}
		return regionResponse(r, http.StatusUnavailableForLegalReasons, `{"error":"unavailable_in_region"}`), nil
	}))

	req, _ := http.NewRequest(http.MethodPost, "https://vpn.mozilla.org/api/v1/fpn/activate?account=one", nil)
	req.Header.Set("Authorization", "Bearer fixture")
	resp, err := do(req)
	if err != nil || resp.StatusCode != http.StatusOK {
		t.Fatalf("doubled request failed: %v", err)
	}
	resp.Body.Close()
	if retried == nil {
		t.Fatal("doubled path was not requested")
	}
	if retried.Method != http.MethodPost || retried.URL.RawQuery != "account=one" || retried.Header.Get("Authorization") != "Bearer fixture" {
		t.Fatalf("retry changed the request: method=%s query=%q auth=%q", retried.Method, retried.URL.RawQuery, retried.Header.Get("Authorization"))
	}
}

func TestRegionRecoveryReplaces451WithReadableSuccessfulResponse(t *testing.T) {
	previous := controlplane.Transport()
	t.Cleanup(func() { controlplane.SetTransport(previous); SetRegionRecovery(nil) })
	controlplane.SetTransport(regionRoundTrip(func(r *http.Request) (*http.Response, error) {
		return regionResponse(r, http.StatusUnavailableForLegalReasons, `{"error":"unavailable_in_region"}`), nil
	}))
	SetRegionRecovery(func(r *http.Request) (*http.Response, error) {
		return regionResponse(r, http.StatusOK, `{"subscribed":true}`), nil
	})
	info, err := FetchUserInfo(t.Context(), DefaultEndpoint, "fixture")
	if err != nil || !info.Subscribed {
		t.Fatalf("successful recovery was lost: %v", err)
	}
}
