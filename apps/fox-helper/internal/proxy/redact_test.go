package proxy

import (
	"net/http"
	"strings"
	"testing"

	"dicodeping/fox/internal/logx"
)

func TestLogErrRedactsConnectHTTPBodyUnlessVerbose(t *testing.T) {
	previous := logx.Verbose.Load()
	t.Cleanup(func() { logx.Verbose.Store(previous) })

	err := &proxyConnectHTTPError{
		statusCode: http.StatusBadGateway,
		status:     "502 Bad Gateway",
		body:       "target example.com failed",
	}

	logx.Verbose.Store(false)
	if got := logx.Err(err); strings.Contains(got, "example.com") {
		t.Fatalf("expected default log error to redact CONNECT body, got %q", got)
	}

	logx.Verbose.Store(true)
	if got := logx.Err(err); !strings.Contains(got, "example.com") {
		t.Fatalf("expected verbose log error to keep CONNECT body, got %q", got)
	}
}
