package guardian

import (
	"net/http"
	"testing"
)

func TestParseProxyUsage(t *testing.T) {
	header := func(kv ...string) http.Header {
		h := make(http.Header)
		for i := 0; i < len(kv); i += 2 {
			h.Set(kv[i], kv[i+1])
		}
		return h
	}

	unlimited, err := parseProxyUsage(header("X-Quota-Unlimited", "true"))
	if err != nil || !unlimited.Unlimited || unlimited.Exhausted() {
		t.Fatalf("unlimited usage: %#v %v", unlimited, err)
	}

	usage, err := parseProxyUsage(header("X-Quota-Limit", "53687091200", "X-Quota-Remaining", "1024", "X-Quota-Reset", "2026-11-01T00:00:00Z"))
	if err != nil || usage.Limit != 53687091200 || usage.Remaining != 1024 || usage.Exhausted() {
		t.Fatalf("finite usage: %#v %v", usage, err)
	}

	for name, h := range map[string]http.Header{
		"missing reset":       header("X-Quota-Limit", "10", "X-Quota-Remaining", "5"),
		"negative remaining":  header("X-Quota-Limit", "10", "X-Quota-Remaining", "-1", "X-Quota-Reset", "2026-11-01T00:00:00Z"),
		"remaining over max":  header("X-Quota-Limit", "10", "X-Quota-Remaining", "11", "X-Quota-Reset", "2026-11-01T00:00:00Z"),
		"invalid reset value": header("X-Quota-Limit", "10", "X-Quota-Remaining", "5", "X-Quota-Reset", "next month"),
	} {
		if _, err := parseProxyUsage(h); err == nil {
			t.Fatalf("%s: expected an error", name)
		}
	}
}
