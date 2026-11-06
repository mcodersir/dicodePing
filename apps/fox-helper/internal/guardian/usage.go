package guardian

import (
	"fmt"
	"net/http"
	"strconv"
	"strings"
	"time"
)

// ProxyUsage is the quota state Guardian reports in X-Quota-* headers.
type ProxyUsage struct {
	Unlimited bool
	Limit     int64
	Remaining int64
	Reset     time.Time
}

// Exhausted reports whether no quota is left for the current period.
func (u *ProxyUsage) Exhausted() bool {
	return u != nil && !u.Unlimited && u.Remaining <= 0
}

// parseProxyUsage parses the X-Quota-* headers like Firefox's ProxyUsage:
// X-Quota-Unlimited: true needs nothing else; otherwise limit, remaining,
// and reset must all be present and consistent.
func parseProxyUsage(h http.Header) (*ProxyUsage, error) {
	if strings.EqualFold(strings.TrimSpace(h.Get("X-Quota-Unlimited")), "true") {
		return &ProxyUsage{Unlimited: true}, nil
	}
	rawLimit := strings.TrimSpace(h.Get("X-Quota-Limit"))
	rawRemaining := strings.TrimSpace(h.Get("X-Quota-Remaining"))
	rawReset := strings.TrimSpace(h.Get("X-Quota-Reset"))
	if rawLimit == "" || rawRemaining == "" || rawReset == "" {
		return nil, fmt.Errorf("quota headers missing")
	}
	limit, err := strconv.ParseInt(rawLimit, 10, 64)
	if err != nil || limit < 0 {
		return nil, fmt.Errorf("invalid X-Quota-Limit")
	}
	remaining, err := strconv.ParseInt(rawRemaining, 10, 64)
	if err != nil || remaining < 0 {
		return nil, fmt.Errorf("invalid X-Quota-Remaining")
	}
	if remaining > limit {
		return nil, fmt.Errorf("X-Quota-Remaining exceeds X-Quota-Limit")
	}
	reset, err := parseQuotaReset(rawReset)
	if err != nil {
		return nil, err
	}
	return &ProxyUsage{Limit: limit, Remaining: remaining, Reset: reset}, nil
}

func parseQuotaReset(value string) (time.Time, error) {
	if t, err := time.Parse(time.RFC3339Nano, value); err == nil {
		return t, nil
	}
	if seconds, err := strconv.ParseInt(value, 10, 64); err == nil && seconds > 0 {
		return time.Unix(seconds, 0), nil
	}
	return time.Time{}, fmt.Errorf("invalid X-Quota-Reset")
}

// ParseProxyUsage parses Guardian's X-Quota-* response headers.
func ParseProxyUsage(h http.Header) (*ProxyUsage, error) {
	return parseProxyUsage(h)
}
