package proxy

import (
	"testing"
)

func TestProxySessionsUpdateBearerToken(t *testing.T) {
	t.Parallel()

	h2Session := &h2ProxySession{token: "old-token"}
	if err := h2Session.UpdateToken("new-token"); err != nil {
		t.Fatalf("h2 UpdateToken returned error: %v", err)
	}
	if got := h2Session.bearerToken(); got != "new-token" {
		t.Fatalf("expected h2 token update, got %q", got)
	}

	h3Session := &h3ProxySession{token: "old-token"}
	if err := h3Session.UpdateToken("new-token"); err != nil {
		t.Fatalf("h3 UpdateToken returned error: %v", err)
	}
	if got := h3Session.bearerToken(); got != "new-token" {
		t.Fatalf("expected h3 token update, got %q", got)
	}
}
