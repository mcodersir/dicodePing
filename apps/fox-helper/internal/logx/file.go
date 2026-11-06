package logx

import (
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"dicodeping/fox/internal/securefile"
)

// The log folder holds one file per local day, arman-vpn-YYYY-MM-DD.log,
// for the last keepLogDays days: when the eighth day starts, the oldest file
// is deleted. A day's file stops growing at maxDayBytes (a safety limit that
// only verbose logging under heavy traffic reaches). Tests change these.
var (
	keepLogDays       = 7
	maxDayBytes int64 = 10 << 20
	now               = time.Now
)

// fileCheckInterval spaces the checks that the day's file is still in the
// folder. A file deleted while open (by hand, or by another copy) keeps
// taking writes that nobody can read; the writer then opens a new one.
const fileCheckInterval = 10 * time.Second

const (
	logFilePrefix = "arman-vpn"
	// The day files' name before 1.0.9, when the program was called
	// Firefox VPN; they go as the others do.
	legacyLogFilePrefix = "firefox-vpn"
	logFileSuffix       = ".log"
	dayLayout           = "2006-01-02"
)

// DayFile returns the log file of the local day of t in dir.
func DayFile(dir string, t time.Time) string {
	return filepath.Join(dir, logFilePrefix+"-"+t.Format(dayLayout)+logFileSuffix)
}

// dailyFile writes to the current day's log file and moves to the next
// file when the day changes. Several processes may append to the same file
// (a tray and a status screen); openLogAppend lets one of them delete an
// old file while another still holds it open.
type dailyFile struct {
	mu      sync.Mutex
	dir     string
	day     string
	file    *os.File
	size    int64
	full    bool
	checked time.Time
}

func openDailyFile(dir string) (*dailyFile, error) {
	if err := securefile.EnsurePrivateDir(dir); err != nil {
		return nil, err
	}
	f := &dailyFile{dir: dir}
	if err := f.open(now()); err != nil {
		return nil, err
	}
	return f, nil
}

func (f *dailyFile) open(t time.Time) error {
	file, err := openLogAppend(DayFile(f.dir, t))
	if err != nil {
		return err
	}
	info, err := file.Stat()
	if err != nil {
		_ = file.Close()
		return err
	}
	f.file, f.size, f.day, f.full, f.checked = file, info.Size(), t.Format(dayLayout), false, t
	pruneLogs(f.dir, t)
	return nil
}

func (f *dailyFile) Write(p []byte) (int, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	t := now()
	if f.file != nil && t.Sub(f.checked) >= fileCheckInterval {
		f.checked = t
		if !f.inFolder() {
			_ = f.file.Close()
			f.file = nil
		}
	}
	if t.Format(dayLayout) != f.day || f.file == nil {
		if f.file != nil {
			_ = f.file.Close()
			f.file = nil
		}
		if err := f.open(t); err != nil {
			return 0, err
		}
	}
	if f.full {
		return len(p), nil
	}
	if f.size+int64(len(p)) > maxDayBytes {
		f.full = true
		notice := fmt.Sprintf("%s WARN  the log file reached %d MiB; lines are dropped until tomorrow\n", t.Format(time.RFC3339), maxDayBytes>>20)
		_, _ = f.file.WriteString(notice)
		return len(p), nil
	}
	n, err := f.file.Write(p)
	f.size += int64(n)
	return n, err
}

// inFolder reports whether the open file is still the day's file in the
// folder.
func (f *dailyFile) inFolder() bool {
	ours, err := f.file.Stat()
	if err != nil {
		return false
	}
	current, err := os.Stat(filepath.Join(f.dir, logFilePrefix+"-"+f.day+logFileSuffix))
	return err == nil && os.SameFile(ours, current)
}

func (f *dailyFile) Close() error {
	f.mu.Lock()
	defer f.mu.Unlock()
	if f.file == nil {
		return errors.New("log file closed")
	}
	err := f.file.Close()
	f.file = nil
	return err
}

// pruneLogs deletes the day files older than keepLogDays days counted back
// from today, and log files of other names left by older versions. Other
// files in the folder are kept.
func pruneLogs(dir string, today time.Time) {
	entries, err := os.ReadDir(dir)
	if err != nil {
		return
	}
	y, m, d := today.Date()
	oldest := time.Date(y, m, d-(keepLogDays-1), 0, 0, 0, 0, today.Location())
	for _, entry := range entries {
		name := entry.Name()
		prefix := logFilePrefix
		if strings.HasPrefix(name, legacyLogFilePrefix) {
			prefix = legacyLogFilePrefix
		}
		if !entry.Type().IsRegular() || !strings.HasPrefix(name, prefix) {
			continue
		}
		day, err := time.ParseInLocation(dayLayout, strings.TrimSuffix(strings.TrimPrefix(name, prefix+"-"), logFileSuffix), today.Location())
		if err == nil && strings.HasSuffix(name, logFileSuffix) && !day.Before(oldest) {
			continue
		}
		_ = os.Remove(filepath.Join(dir, name))
	}
}

// EnableFile writes log lines to the daily log files in dir, and also to
// stderr when a console shows it. A service or tray process has no usable
// stderr, and io.MultiWriter would stop at its first failing writer.
func EnableFile(dir string, console bool) bool {
	f, err := openDailyFile(dir)
	if err != nil {
		Warn("opening the log file failed dir=%s err=%s", dir, Err(err))
		return false
	}
	if console {
		SetOutput(io.MultiWriter(f, os.Stderr))
	} else {
		SetOutput(f)
	}
	return true
}
