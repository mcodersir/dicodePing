package fxa

import (
	"context"
	"errors"
	"net/http"
	"strings"
	"testing"
)

func TestRegisterDeviceUsesRefreshTokenAndName(t *testing.T) {
	useFxaFixture(t, func(r *http.Request, body map[string]any) (int, string) {
		if r.Method != http.MethodPost || r.URL.Path != "/v1/account/device" {
			return 500, "unexpected request"
		}
		if r.Header.Get("Authorization") != "Bearer refresh-1" {
			return 401, `{"errno":110,"message":"Invalid authentication token"}`
		}
		if body["name"] != DeviceName || body["type"] != "desktop" {
			return 400, `{"errno":107}`
		}
		if id, ok := body["id"]; ok {
			return 200, `{"id":"` + id.(string) + `","name":"` + DeviceName + `","type":"desktop"}`
		}
		return 200, `{"id":"abcd01","name":"` + DeviceName + `","type":"desktop"}`
	})
	device, err := RegisterDevice(context.Background(), "refresh-1", "", DeviceName)
	if err != nil || device.ID != "abcd01" || device.Name != "Firefox's built-in VPN" {
		t.Fatalf("register: %+v %v", device, err)
	}
	if device, err = RegisterDevice(context.Background(), "refresh-1", "abcd01", DeviceName); err != nil || device.ID != "abcd01" {
		t.Fatalf("update: %+v %v", device, err)
	}
	if _, err := RegisterDevice(context.Background(), "revoked", "", DeviceName); !errors.Is(err, ErrReauthRequired) {
		t.Fatalf("a rejected token must ask for a new sign-in, got %v", err)
	}
}

// The sign-in session ends once its OAuth tokens exist, so the account's
// connected services do not list it as "unknown".
func TestDestroySessionSignsWithTheSessionToken(t *testing.T) {
	session := strings.Repeat("ab", 32)
	called := 0
	useFxaFixture(t, func(r *http.Request, body map[string]any) (int, string) {
		if r.Method != http.MethodPost || r.URL.Path != "/v1/session/destroy" {
			return 500, "unexpected request"
		}
		if !strings.HasPrefix(r.Header.Get("Authorization"), "Hawk ") {
			return 401, `{"errno":110}`
		}
		called++
		return 200, `{}`
	})
	if err := DestroySession(context.Background(), session); err != nil || called != 1 {
		t.Fatalf("destroy: %v (called %d)", err, called)
	}
}
