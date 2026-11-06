package accounts

import (
	"path/filepath"
	"testing"
	"time"

	"dicodeping/fox/internal/fxa"
)

// The manager's saves keep the device record that another writer stored
// after the manager loaded its copy; erasing it made every start register
// a new "Firefox's built-in VPN" entry in the account's connected services.
func TestManagerKeepsDeviceRecord(t *testing.T) {
	dir := t.TempDir()
	store, err := OpenStore(dir)
	if err != nil {
		t.Fatal(err)
	}
	acc, _, err := store.Add("a@example.com", &fxa.SavedTokens{AccessToken: "access", RefreshToken: "refresh"}, time.Now())
	if err != nil {
		t.Fatal(err)
	}
	mgr, err := NewManager(store, []string{acc.ID}, Policy{ThresholdPercent: 90}, filepath.Join(dir, "state.json"))
	if err != nil {
		t.Fatal(err)
	}

	stored, _ := store.Get(acc.ID)
	stored.DeviceID, stored.DeviceToken = "dev-1", "fingerprint"
	if err := store.Save(stored); err != nil {
		t.Fatal(err)
	}

	if _, err := mgr.ObserveUsage(acc.ID, Usage{LimitBytes: 100, RemainingBytes: 90}); err != nil {
		t.Fatal(err)
	}
	if err := mgr.MarkUnavailable(acc.ID, Why{Code: ReasonSignInRetry, Text: "test", Detail: "timeout"}, time.Now().Add(time.Minute)); err != nil {
		t.Fatal(err)
	}
	// The reason's code and detail are kept for the apps, next to the text.
	if marked, _ := store.Get(acc.ID); marked.Reason != "test" || marked.ReasonCode != ReasonSignInRetry || marked.ReasonDetail != "timeout" {
		t.Fatalf("reason kept: %+v", marked)
	}
	if err := mgr.Activate(acc.ID); err != nil {
		t.Fatal(err)
	}
	got, err := store.Get(acc.ID)
	if err != nil {
		t.Fatal(err)
	}
	if got.DeviceID != "dev-1" || got.DeviceToken != "fingerprint" {
		t.Fatalf("device record lost: %+v", got)
	}
	if got.Reason != "" || got.ReasonCode != "" || got.ReasonDetail != "" {
		t.Fatalf("a usable account has no reason: %+v", got)
	}
	if got.Usage == nil || got.Usage.RemainingBytes != 90 || got.Status != StatusReady {
		t.Fatalf("manager fields not saved: %+v", got)
	}
}
