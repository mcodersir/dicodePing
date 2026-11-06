package securefile

import (
	"os"
	"path/filepath"
	"runtime"
	"testing"
)

func TestWritePrivateReplacesContentAndTightensPermissions(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "tokens.json")

	if err := os.WriteFile(path, []byte("old"), 0644); err != nil {
		t.Fatalf("creating old token file: %v", err)
	}
	if err := WritePrivate(path, []byte("new")); err != nil {
		t.Fatalf("WritePrivate returned error: %v", err)
	}

	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("reading token file: %v", err)
	}
	if string(data) != "new" {
		t.Fatalf("expected replaced content, got %q", data)
	}

	if runtime.GOOS == "windows" {
		return
	}
	info, err := os.Stat(path)
	if err != nil {
		t.Fatalf("stat token file: %v", err)
	}
	if got := info.Mode().Perm(); got != 0600 {
		t.Fatalf("expected token file mode 0600, got %o", got)
	}
}
