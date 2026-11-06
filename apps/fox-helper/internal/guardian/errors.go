package guardian

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"strconv"
	"strings"
	"time"

	"dicodeping/fox/internal/controlplane"
)

var (
	// ErrQuotaExceeded signals that the account's monthly proxy quota is
	// exhausted (Guardian responds with HTTP 429).
	ErrQuotaExceeded = errors.New("quota exceeded")

	// ErrTokenInvalid signals that Guardian rejected the request with HTTP
	// 401 (access token rejected) or 403 (account not entitled). Callers
	// with a session token pool rotate to the next token on this error.
	ErrTokenInvalid = errors.New("token invalid")

	// ErrNotEntitled signals HTTP 403: the access token is valid but the
	// account has no proxy entitlement yet; activation can grant it. It
	// is reported together with ErrTokenInvalid.
	ErrNotEntitled = errors.New("account not entitled")

	// ErrRegionUnavailable signals HTTP 451: Guardian does not serve the
	// region of the requesting address. Retrying from the same address
	// does not help.
	ErrRegionUnavailable = errors.New("Guardian does not serve this region")

	// ErrServer signals an HTTP 5xx answer from Guardian.
	ErrServer = errors.New("Guardian server error")
)

// HTTPError carries a non-200 Guardian response. errors.Is matches
// the sentinel errors above according to the status code.
type HTTPError struct {
	Operation  string
	StatusCode int
	Body       string
	// RetryAfter is the delay requested by a Retry-After header, or zero.
	RetryAfter time.Duration
	// Usage holds valid quota headers sent with the error, if any.
	Usage *ProxyUsage
}

func (e *HTTPError) Error() string {
	if kind := e.kind(); kind != nil {
		return fmt.Sprintf("%s returned HTTP %d (%s): %s", e.Operation, e.StatusCode, kind, e.Body)
	}
	return fmt.Sprintf("%s returned HTTP %d: %s", e.Operation, e.StatusCode, e.Body)
}

func (e *HTTPError) kind() error {
	switch {
	case e.StatusCode == http.StatusUnauthorized:
		return ErrTokenInvalid
	case e.StatusCode == http.StatusForbidden:
		return ErrNotEntitled
	case e.StatusCode == http.StatusTooManyRequests:
		return ErrQuotaExceeded
	case e.StatusCode == http.StatusUnavailableForLegalReasons:
		return ErrRegionUnavailable
	case e.StatusCode >= 500 && e.StatusCode <= 599:
		return ErrServer
	}
	return nil
}

func (e *HTTPError) Unwrap() []error {
	switch kind := e.kind(); kind {
	case nil:
		return nil
	case ErrNotEntitled:
		return []error{ErrTokenInvalid, ErrNotEntitled}
	default:
		return []error{kind}
	}
}

// IsTransient reports whether a Guardian request failed in a way
// that a prompt retry can fix: a transport error or an HTTP 5xx answer.
// Context cancellation and every other HTTP status are not transient.
func IsTransient(err error) bool {
	if err == nil || errors.Is(err, context.Canceled) {
		return false
	}
	var httpErr *HTTPError
	if errors.As(err, &httpErr) {
		return errors.Is(err, ErrServer)
	}
	var claimsErr *proxyPassFormatError
	return !errors.As(err, &claimsErr)
}

// RetryAfter returns the server-requested retry delay carried by err,
// or zero.
func RetryAfter(err error) time.Duration {
	var httpErr *HTTPError
	if errors.As(err, &httpErr) {
		return httpErr.RetryAfter
	}
	return 0
}

// UsageFromError returns the quota state carried by err, or nil.
func UsageFromError(err error) *ProxyUsage {
	var httpErr *HTTPError
	if errors.As(err, &httpErr) {
		return httpErr.Usage
	}
	return nil
}

// proxyPassFormatError marks a 200 response whose pass cannot be used; a
// retry would only fetch another malformed pass.
type proxyPassFormatError struct{ err error }

func (e *proxyPassFormatError) Error() string { return e.err.Error() }
func (e *proxyPassFormatError) Unwrap() error { return e.err }

func newHTTPError(operation string, resp *http.Response) *HTTPError {
	err := &HTTPError{
		Operation:  operation,
		StatusCode: resp.StatusCode,
		Body:       controlplane.ReadErrorBody(resp.Body),
	}
	if resp.StatusCode == http.StatusTooManyRequests || resp.StatusCode >= 500 {
		err.RetryAfter = parseRetryAfter(resp.Header.Get("Retry-After"), time.Now())
	}
	if usage, usageErr := parseProxyUsage(resp.Header); usageErr == nil {
		err.Usage = usage
	}
	return err
}

// parseRetryAfter accepts delay-seconds or an HTTP-date.
func parseRetryAfter(value string, now time.Time) time.Duration {
	value = strings.TrimSpace(value)
	if value == "" {
		return 0
	}
	if seconds, err := strconv.ParseInt(value, 10, 64); err == nil {
		if seconds <= 0 {
			return 0
		}
		return time.Duration(seconds) * time.Second
	}
	if at, err := http.ParseTime(value); err == nil && at.After(now) {
		return at.Sub(now)
	}
	return 0
}
