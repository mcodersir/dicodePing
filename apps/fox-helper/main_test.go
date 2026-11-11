package main

import (
	"context"
	"crypto/sha256"
	"dicodeping/fox/internal/controlplane"
	"dicodeping/fox/internal/fxa"
 "dicodeping/fox/internal/guardian"
	"encoding/base64"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

type roundTripFunc func(*http.Request) (*http.Response, error)

func (f roundTripFunc) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }

// Real HTTP fixture verifies the adapter reaches the alternate Mozilla grant
// after the exact HTTP 406 regression, including one-time state and PKCE.
func TestBrowserSession406UsesArmanCodeGrant(t *testing.T) {
	var challenge, state string
	calls := 0
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls++
		var data map[string]string
		if r.Method == http.MethodPost {
			if err := json.NewDecoder(r.Body).Decode(&data); err != nil {
				t.Error(err)
			}
		}
		switch {
		case r.URL.Path == "/v1/recovery_email/status":
			io.WriteString(w, `{"verified":true}`)
		case r.URL.Path == "/v1/oauth/token" && data["grant_type"] == "fxa-credentials":
			if !strings.HasPrefix(r.Header.Get("Authorization"), "Hawk ") {
				t.Error("missing session authentication")
			}
			w.WriteHeader(406)
		case r.URL.Path == "/v1/oauth/authorization":
			challenge, state = data["code_challenge"], data["state"]
			if challenge == "" || state == "" || data["code_challenge_method"] != "S256" || !strings.HasPrefix(r.Header.Get("Authorization"), "Hawk ") {
				t.Error("invalid authorization request")
			}
			json.NewEncoder(w).Encode(map[string]string{"code": "single-use-code", "state": state})
		case r.URL.Path == "/v1/token":
			sum := sha256.Sum256([]byte(data["code_verifier"]))
			if base64.RawURLEncoding.EncodeToString(sum[:]) != challenge || data["code"] != "single-use-code" || data["grant_type"] != "authorization_code" {
				t.Error("PKCE verifier/code not bound")
			}
			io.WriteString(w, `{"access_token":"new-access-fixture","refresh_token":"new-refresh-fixture","expires_in":3600}`)
		default:
			t.Errorf("unexpected request %s", r.URL.Path)
			w.WriteHeader(500)
		}
	}))
	defer server.Close()
	original := controlplane.Transport()
	t.Cleanup(func() { controlplane.SetTransport(original) })
	controlplane.SetTransport(roundTripFunc(func(r *http.Request) (*http.Response, error) {
		copy := r.Clone(r.Context())
		u := *r.URL
		copy.URL = &u
		copy.URL.Scheme = "http"
		copy.URL.Host = server.Listener.Addr().String()
		return http.DefaultTransport.RoundTrip(copy)
	}))
	e := &engine{}
	if err := e.session(context.Background(), "fixture@example.test", strings.Repeat("12", 32)); err != nil {
		t.Fatal(failure(err))
	}
	if calls != 4 || e.state.AccessToken != "new-access-fixture" || e.state.RefreshToken != "new-refresh-fixture" || e.state.SessionToken != "" {
		t.Fatal("alternate grant was not committed to the private state")
	}
}

func TestRefresh406UsesOtherMozillaEndpoint(t *testing.T) {
	original := controlplane.Transport()
	t.Cleanup(func() { controlplane.SetTransport(original) })
	hosts := []string{}
	controlplane.SetTransport(roundTripFunc(func(r *http.Request) (*http.Response, error) {
		hosts = append(hosts, r.URL.Host)
		status, body := 406, ""
		if r.URL.Host == "oauth.accounts.firefox.com" {
			status = 200
			body = `{"access_token":"refreshed-fixture","expires_in":3600}`
		}
		return &http.Response{StatusCode: status, Header: make(http.Header), Body: io.NopCloser(strings.NewReader(body)), Request: r}, nil
	}))
	token, err := fxa.RefreshToken(context.Background(), "preserved-refresh-fixture")
	if err != nil {
		t.Fatal(failure(err))
	}
	if len(hosts) != 2 || token.AccessToken != "refreshed-fixture" || token.RefreshToken != "preserved-refresh-fixture" {
		t.Fatal("refresh fallback lost the stored session")
	}
}

func TestUnconfirmedSessionDoesNotBecomeAnAccount(t *testing.T) {
	original := controlplane.Transport()
	t.Cleanup(func() { controlplane.SetTransport(original) })
	controlplane.SetTransport(roundTripFunc(func(r *http.Request) (*http.Response, error) {
		return &http.Response{StatusCode: 400, Header: make(http.Header), Body: io.NopCloser(strings.NewReader(`{"errno":104,"token":"do-not-log"}`)), Request: r}, nil
	}))
	e := &engine{}
	err := e.session(context.Background(), "fixture@example.test", strings.Repeat("12", 32))
	if err == nil || e.state.AccessToken != "" || failure(err).Error != "session_unconfirmed" || strings.Contains(failure(err).Message, "do-not-log") {
		t.Fatal("verification or redaction contract failed")
	}
}

func TestUnlimitedAllowanceIsPreservedInThePrivateProtocol(t *testing.T) {
    info := accountUsage(&guardian.ProxyUsage{Unlimited: true})
    if info.QuotaUnlimited == nil || !*info.QuotaUnlimited || info.QuotaMax != nil { t.Fatal("provider unlimited status was lost") }
    limited := accountUsage(&guardian.ProxyUsage{Limit: 100, Remaining: 40})
    if limited.QuotaUnlimited == nil || *limited.QuotaUnlimited || *limited.QuotaRemaining != 40 { t.Fatal("limited allowance was changed") }
    if accountUsage(nil).QuotaUnlimited != nil { t.Fatal("an unknown allowance was silently declared unlimited") }
}
