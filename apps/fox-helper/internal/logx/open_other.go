//go:build !windows

package logx

import "os"

// openLogAppend opens path for appending; POSIX allows deleting open files.
func openLogAppend(path string) (*os.File, error) {
	return os.OpenFile(path, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o600)
}
