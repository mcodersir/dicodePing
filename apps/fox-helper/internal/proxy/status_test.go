package proxy

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"testing"
	"time"

	"dicodeping/fox/internal/guardian"
)

func TestProxyControllerWritesStatusFile(t *testing.T) {
	t.Parallel()

	dir := t.TempDir()
	statusFile := filepath.Join(dir, "status.json")
	controller := &Controller{
		statusFile: statusFile,
		current: &managedSession{
			session:   &fakeProxySession{},
			expiresAt: time.Now().Add(10 * time.Minute),
			accepting: true,
		},
	}

	controller.writeStatus("startup")
	controller.writeStatus("renewed")

	data, err := os.ReadFile(statusFile)
	if err != nil {
		t.Fatalf("ReadFile returned error: %v", err)
	}
	var status RuntimeStatus
	if err := json.Unmarshal(data, &status); err != nil {
		t.Fatalf("json.Unmarshal returned error: %v", err)
	}
	if status.Reason != "renewed" {
		t.Fatalf("expected reason renewed, got %q", status.Reason)
	}
	if status.ProxyPassExpiresAt == "" {
		t.Fatal("expected proxy_pass_expires_at to be populated")
	}
	if !status.Accepting {
		t.Fatal("expected accepting=true")
	}
}

func TestProxyControllerStatusReportsQuotaAndFailure(t *testing.T) {
	t.Parallel()

	controller := &Controller{
		current: &managedSession{expiresAt: time.Now().Add(time.Minute), accepting: true},
		usage:   &guardian.ProxyUsage{Limit: 100, Remaining: 40, Reset: time.Date(2026, 11, 1, 0, 0, 0, 0, time.UTC)},
	}
	controller.recordRenewalOutcome(fmt.Errorf("x: %w", guardian.ErrRegionUnavailable), time.Now().Add(time.Minute))
	status := controller.CurrentStatus("renewal_failed")
	if status.LastError != "region_unavailable" || status.NextAttemptAt == "" {
		t.Fatalf("expected failure fields, got %#v", status)
	}
	if status.QuotaRemainingBytes == nil || *status.QuotaRemainingBytes != 40 || status.QuotaResetAt != "2026-11-01T00:00:00Z" {
		t.Fatalf("expected quota fields, got %#v", status)
	}

	controller.recordRenewalOutcome(nil, time.Time{})
	if status := controller.CurrentStatus("token_updated"); status.LastError != "" || status.NextAttemptAt != "" {
		t.Fatalf("expected failure fields to clear after success, got %#v", status)
	}
}
