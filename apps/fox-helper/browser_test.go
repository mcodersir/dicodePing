package main

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

func TestBrowserSessionUsesFxaGrantAndNeverPostsAPassword(t *testing.T) {
	s := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/oauth/token" || !strings.HasPrefix(r.Header.Get("Authorization"), "Hawk ") {
			t.Error("Browser session did not use the FxA credential grant")
		}
		var b map[string]any
		json.NewDecoder(r.Body).Decode(&b)
		if b["grant_type"] != "fxa-credentials" || b["password"] != nil || b["authPW"] != nil {
			t.Error("Wrong browser grant")
		}
		io.WriteString(w, `{"access_token":"fxa-access","refresh_token":"fxa-refresh","expires_in":3600}`)
	}))
	defer s.Close()
	p := newProvider(State{})
	p.authURL = s.URL
	if e := p.browserLogin(context.Background(), "fixture@example.test", strings.Repeat("12", 32)); e != nil {
		t.Fatal(e)
	}
	if p.state.SessionToken != "" || p.state.RefreshToken != "fxa-refresh" || p.state.Email != "fixture@example.test" {
		t.Fatal("Incomplete or leaked browser session")
	}
	if e := p.browserLogin(context.Background(), "fixture@example.test", "guardian.jwt.token"); e == nil {
		t.Fatal("Guardian JWT accepted as a browser session")
	}
}
func TestExpiredAccessTokenRefreshesAtDedicatedOAuthServer(t *testing.T) {
	calls := 0
	s := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls++
		if r.URL.Path != "/token" {
			t.Error("Wrong OAuth discovery endpoint")
		}
		io.WriteString(w, `{"access_token":"new-access","expires_in":3600}`)
	}))
	defer s.Close()
	p := newProvider(State{Email: "fixture@example.test", AccessToken: "old", RefreshToken: "keep-refresh", ExpiresAt: 0})
	p.oauthURL = s.URL
	p.authURL = "http://unused.invalid"
	if e := p.ensureAuth(context.Background()); e != nil {
		t.Fatal(e)
	}
	if calls != 1 || p.state.AccessToken != "new-access" || p.state.RefreshToken != "keep-refresh" {
		t.Fatal("Refresh token lost")
	}
}
func TestRejectedLiveTokenRefreshesBeforeActivation(t *testing.T) {
	activation := 0
	refresh := 0
	oauth := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		refresh++
		io.WriteString(w, `{"access_token":"fresh","expires_in":3600}`)
	}))
	defer oauth.Close()
	guardian := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if strings.HasSuffix(r.URL.Path, "/activate") {
			activation++
			w.WriteHeader(500)
			return
		}
		if strings.HasSuffix(r.URL.Path, "/status") {
			w.WriteHeader(503)
			return
		}
		if r.Header.Get("Authorization") != "Bearer fresh" {
			w.WriteHeader(401)
			return
		}
		io.WriteString(w, `{"token":"working-pass"}`)
	}))
	defer guardian.Close()
	p := newProvider(State{AccessToken: "revoked-early", RefreshToken: "refresh", ExpiresAt: time.Now().Unix() + 3600})
	p.oauthURL = oauth.URL
	p.guardianURL = guardian.URL
	if _, e := p.account(context.Background()); e != nil {
		t.Fatal(e)
	}
	if activation != 0 || refresh != 1 {
		t.Fatal("Activated before renewing a rejected session")
	}
}
func TestUnconfirmedBrowserSessionRequiresWebsiteVerification(t *testing.T) {
	s := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(400); io.WriteString(w, `{"errno":104}`) }))
	defer s.Close()
	p := newProvider(State{})
	p.authURL = s.URL
	e := p.browserLogin(context.Background(), "fixture@example.test", strings.Repeat("01", 32))
	api, ok := e.(*ProviderError)
	if !ok || api.Code != "session_unconfirmed" {
		t.Fatal("Unconfirmed session was accepted")
	}
}
