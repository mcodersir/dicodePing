package accounts

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"dicodeping/fox/internal/fxa"
)

// A folder under accounts/ that holds no readable account (a copy made by
// hand, or an account file left empty by a crash) is skipped with a
// warning; the other accounts still load, and the folder stays.
func TestListSkipsDamagedFolders(t *testing.T) {
	dir := t.TempDir()
	store, err := OpenStore(dir)
	if err != nil {
		t.Fatal(err)
	}
	good, _, err := store.Add("a@example.com", &fxa.SavedTokens{AccessToken: "access", RefreshToken: "refresh"}, time.Now())
	if err != nil {
		t.Fatal(err)
	}
	accountsDir := filepath.Join(dir, "accounts")
	for _, name := range []string{"backup.old", "abcdef12"} {
		if err := os.MkdirAll(filepath.Join(accountsDir, name), 0o700); err != nil {
			t.Fatal(err)
		}
	}
	// An empty account file, as a power cut can leave.
	if err := os.WriteFile(filepath.Join(accountsDir, "abcdef12", accountFileName), nil, 0o600); err != nil {
		t.Fatal(err)
	}
	var warnings []string
	defer func(old func(string)) { Warn = old }(Warn)
	Warn = func(s string) { warnings = append(warnings, s) }

	list, err := store.List()
	if err != nil {
		t.Fatalf("a damaged folder must not stop the listing: %v", err)
	}
	if len(list) != 1 || list[0].ID != good.ID {
		t.Fatalf("want only the good account, got %+v", list)
	}
	if len(warnings) != 2 || !strings.Contains(strings.Join(warnings, "\n"), "backup.old") {
		t.Fatalf("want a warning per skipped folder, got %q", warnings)
	}
	if _, err := os.Stat(filepath.Join(accountsDir, "abcdef12")); err != nil {
		t.Fatal("a skipped folder must stay for the user")
	}
}
