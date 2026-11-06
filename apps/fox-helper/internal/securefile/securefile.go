// Package securefile writes files that hold secrets or personal data.
package securefile

import (
	"os"
	"path/filepath"
	"runtime"
	"time"
)

// WritePrivate replaces path with data through a temporary file in the same
// directory, readable and writable only by the owner (0600 on POSIX; Windows
// keeps the default ACL of the user's profile directory). The data reaches
// the disk before the rename (and the rename before it returns, on POSIX),
// so a crash or a power cut leaves either the old file or the new one, never
// an empty one. The old file is never deleted first: when Windows refuses
// the rename, the old file stays and an error is returned.
func WritePrivate(path string, data []byte) error {
	dir := filepath.Dir(path)
	tmp, err := os.CreateTemp(dir, filepath.Base(path)+".tmp-*")
	if err != nil {
		return err
	}
	tmpPath := tmp.Name()
	defer os.Remove(tmpPath)

	if err := tmp.Chmod(0600); err != nil {
		_ = tmp.Close()
		return err
	}
	if _, err := tmp.Write(data); err != nil {
		_ = tmp.Close()
		return err
	}
	if err := tmp.Sync(); err != nil {
		_ = tmp.Close()
		return err
	}
	if err := tmp.Close(); err != nil {
		return err
	}

	if err := renameReplacing(tmpPath, path); err != nil {
		return err
	}
	syncDir(dir)
	return os.Chmod(path, 0600)
}

// renameAttempts and renameFirstWait bound the retries of a refused rename.
const (
	renameAttempts  = 6
	renameFirstWait = 20 * time.Millisecond
)

// renameReplacing renames from over to. Windows refuses while another
// program, typically an antivirus or indexer scan of the new file, holds
// either file open; that lasts moments, so the rename is tried again with a
// growing wait (about 0.6 s in all).
func renameReplacing(from, to string) error {
	wait := renameFirstWait
	var err error
	for attempt := 0; attempt < renameAttempts; attempt++ {
		if err = os.Rename(from, to); err == nil {
			return nil
		}
		if runtime.GOOS != "windows" {
			return err
		}
		time.Sleep(wait)
		wait *= 2
	}
	return err
}

// syncDir makes a rename in dir durable on POSIX; Windows has no directory
// sync and needs none for NTFS's journaled renames.
func syncDir(dir string) {
	if runtime.GOOS == "windows" {
		return
	}
	if f, err := os.Open(dir); err == nil {
		_ = f.Sync()
		_ = f.Close()
	}
}

// EnsurePrivateDir creates dir and its parents with owner-only permissions.
func EnsurePrivateDir(dir string) error {
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return err
	}
	return os.Chmod(dir, 0o700)
}
