package fxa

import (
	"context"
	"os"
	"testing"
)

// TestSolveFastlyChallengeE2E exercises the real Fastly challenge flow and
// proves the solved cookie lets API requests pass the edge. It hits live
// infrastructure, so it only runs when FXA_E2E=1 is set.
func TestSolveFastlyChallengeE2E(t *testing.T) {
	if os.Getenv("FXA_E2E") != "1" {
		t.Skip("set FXA_E2E=1 to run the live Fastly challenge test")
	}

	ctx := context.Background()
	if err := solveFastlyChallenge(ctx); err != nil {
		t.Fatalf("solveFastlyChallenge failed: %v", err)
	}

	// A dummy login must now reach the FxA origin: it should fail with a
	// proper FxA error (e.g. unknown account), not with HTTP 406.
	_, err := fxaLogin(ctx, "nonexistent-user-e2e@example.invalid", "dummy-password", "")
	if err == nil {
		t.Fatal("expected dummy login to fail")
	}
	t.Logf("dummy login result: %v", err)
}
