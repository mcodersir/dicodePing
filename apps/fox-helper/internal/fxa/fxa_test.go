package fxa

import (
	"errors"
	"fmt"
	"testing"
)

func TestFxaAPIErrorClassifiesReauthRequired(t *testing.T) {
	for status, want := range map[int]bool{400: true, 401: true, 403: true, 429: false, 500: false} {
		err := fmt.Errorf("refresh request: %w", newFxaAPIError(status, []byte(`{"errno":110}`)))
		if got := errors.Is(err, ErrReauthRequired); got != want {
			t.Errorf("HTTP %d: errors.Is(ErrReauthRequired) = %v, want %v", status, got, want)
		}
	}
	if errors.Is(newFxaAPIError(400, []byte(`{"errno":107}`)), ErrReauthRequired) {
		t.Error("an invalid-parameter error must not require sign-in")
	}
}

func TestNewFxaAPIErrorParsesErrno(t *testing.T) {
	apiErr := newFxaAPIError(400, []byte(`{"code":400,"errno":107,"message":"Invalid parameter: verificationMethod"}`))
	if apiErr.Errno != fxaErrnoInvalidParameter {
		t.Fatalf("expected errno %d, got %d", fxaErrnoInvalidParameter, apiErr.Errno)
	}

	plain := newFxaAPIError(500, []byte("boom"))
	if plain.Errno != 0 {
		t.Fatalf("expected errno 0 for non-JSON body, got %d", plain.Errno)
	}
}
