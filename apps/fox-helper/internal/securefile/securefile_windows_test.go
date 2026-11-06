//go:build windows

package securefile

import (
	"os"
	"path/filepath"
	"testing"
)

// When Windows refuses the rename (another program holds the file open),
// the old file stays as it was; it is never deleted first.
func TestRefusedRenameKeepsTheOldFile(t *testing.T) {
	path := filepath.Join(t.TempDir(), "config.json")
	if err := os.WriteFile(path, []byte("old"), 0o600); err != nil {
		t.Fatal(err)
	}
	// os.Open shares read and write but not delete, as a scanner may.
	held, err := os.Open(path)
	if err != nil {
		t.Fatal(err)
	}
	if err := WritePrivate(path, []byte("new")); err == nil {
		t.Log("the rename went through despite the open handle")
	}
	_ = held.Close()
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("the old file is gone: %v", err)
	}
	if got := string(data); got != "old" && got != "new" {
		t.Fatalf("the file holds %q", got)
	}
	matches, _ := filepath.Glob(path + ".tmp-*")
	if len(matches) != 0 {
		t.Fatalf("temporary files left: %v", matches)
	}

	// Once the file is free, the write goes through.
	if err := WritePrivate(path, []byte("new")); err != nil {
		t.Fatal(err)
	}
	if data, _ := os.ReadFile(path); string(data) != "new" {
		t.Fatalf("after the retry the file holds %q", data)
	}
}
