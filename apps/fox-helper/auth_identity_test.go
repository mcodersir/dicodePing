package main

import (
	"context"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
)

// Exercise the complete 406 retry and cookie jar. Clearance issued for a
// different User-Agent must not be silently discarded on the sign-in retry.
func TestFxaLoginKeepsChallengeIdentityAndCookie(t *testing.T) {
	var attempts atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("User-Agent") != challengeUA {
			t.Error("FxA identity changed across challenge and retry")
			w.WriteHeader(406)
			return
		}
		cleared := false
		if c, err := r.Cookie("clearance"); err == nil {
			cleared = c.Value == "accepted"
		}
		switch r.URL.Path {
		case "/v1/account/login":
			attempts.Add(1)
			if !cleared {
				w.WriteHeader(406)
				return
			}
			fmt.Fprintf(w, `{"sessionToken":"%s","verified":false,"verificationMethod":"email-2fa"}`, strings.Repeat("01", 32))
		case "/":
			if cleared {
				fmt.Fprint(w, "account service")
				return
			}
			fmt.Fprint(w, `Client Challenge /_fs-ch-fixture`)
		case "/_fs-ch-fixture/script.js":
			fmt.Fprint(w, `init([], "fixture-token", "unused")`)
		case "/_fs-ch-fixture/fst-post-back":
			http.SetCookie(w, &http.Cookie{Name: "clearance", Value: "accepted", Path: "/"})
			fmt.Fprint(w, `{"status":"success"}`)
		default:
			t.Errorf("Unexpected path %s", r.URL.Path)
			w.WriteHeader(404)
		}
	}))
	defer server.Close()
	p := newProvider(State{})
	p.authURL = server.URL + "/v1"
	p.challengeOrigins = []string{server.URL}
	if err := p.login(context.Background(), "fixture@example.test", "test-only-password"); err != nil {
		t.Fatal(err)
	}
	if p.state.SessionToken == "" || p.state.VerificationMethod != "email-2fa" {
		t.Fatal("Email verification step was lost")
	}
	if attempts.Load() != 2 {
		t.Fatalf("Expected one retry, got %d", attempts.Load())
	}
}

func TestFxaUnknownAccountIsNotReportedAsBrowserVerification(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(400); fmt.Fprint(w, `{"errno":102}`) }))
	defer server.Close()
	p := newProvider(State{})
	p.authURL = server.URL
	err := p.login(context.Background(), "fixture@example.test", "test-only-password")
	api, ok := err.(*ProviderError)
	if !ok || api.Code != "account_not_found" || api.Status != 400 {
		t.Fatalf("Wrong error classification: %v", err)
	}
}
