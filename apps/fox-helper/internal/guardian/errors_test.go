package guardian

import (
	"errors"
	"io"
	"net/http"
	"strings"
	"testing"
	"time"
)

func guardianResponse(status int, header http.Header) *http.Response {
	if header == nil {
		header = make(http.Header)
	}
	return &http.Response{StatusCode: status, Header: header, Body: io.NopCloser(strings.NewReader("body"))}
}

func TestHTTPErrorClassifiesStatus(t *testing.T) {
	tests := []struct {
		status    int
		want      []error
		notWant   []error
		transient bool
	}{
		{http.StatusUnauthorized, []error{ErrTokenInvalid}, []error{ErrNotEntitled, ErrQuotaExceeded}, false},
		{http.StatusForbidden, []error{ErrTokenInvalid, ErrNotEntitled}, []error{ErrQuotaExceeded}, false},
		{http.StatusTooManyRequests, []error{ErrQuotaExceeded}, []error{ErrTokenInvalid}, false},
		{http.StatusUnavailableForLegalReasons, []error{ErrRegionUnavailable}, []error{ErrTokenInvalid, ErrServer}, false},
		{http.StatusServiceUnavailable, []error{ErrServer}, []error{ErrTokenInvalid}, true},
		{http.StatusBadRequest, nil, []error{ErrTokenInvalid, ErrServer, ErrQuotaExceeded}, false},
	}
	for _, tc := range tests {
		err := error(newHTTPError("guardian", guardianResponse(tc.status, nil)))
		for _, want := range tc.want {
			if !errors.Is(err, want) {
				t.Errorf("HTTP %d: expected errors.Is(%v)", tc.status, want)
			}
		}
		for _, notWant := range tc.notWant {
			if errors.Is(err, notWant) {
				t.Errorf("HTTP %d: unexpected errors.Is(%v)", tc.status, notWant)
			}
		}
		if got := IsTransient(err); got != tc.transient {
			t.Errorf("HTTP %d: transient=%v, want %v", tc.status, got, tc.transient)
		}
	}
}

func TestHTTPErrorCarriesRetryAfterAndUsage(t *testing.T) {
	header := make(http.Header)
	header.Set("Retry-After", "120")
	header.Set("X-Quota-Limit", "100")
	header.Set("X-Quota-Remaining", "0")
	header.Set("X-Quota-Reset", "2026-11-01T00:00:00Z")
	err := newHTTPError("guardian", guardianResponse(http.StatusTooManyRequests, header))

	if got := RetryAfter(err); got != 2*time.Minute {
		t.Fatalf("expected Retry-After 2m, got %s", got)
	}
	usage := UsageFromError(err)
	if usage == nil || !usage.Exhausted() || usage.Reset.Format(time.RFC3339) != "2026-11-01T00:00:00Z" {
		t.Fatalf("expected exhausted usage with reset, got %#v", usage)
	}
}

func TestParseRetryAfterAcceptsHTTPDate(t *testing.T) {
	now := time.Date(2026, 10, 9, 12, 0, 0, 0, time.UTC)
	if got := parseRetryAfter(now.Add(90*time.Second).Format(http.TimeFormat), now); got != 90*time.Second {
		t.Fatalf("expected 90s, got %s", got)
	}
	if got := parseRetryAfter("soon", now); got != 0 {
		t.Fatalf("expected 0 for invalid value, got %s", got)
	}
}
