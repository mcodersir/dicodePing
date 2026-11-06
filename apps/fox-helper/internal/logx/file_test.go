package logx

import (
	"bytes"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"testing"
	"time"
)

// fakeClock replaces the log clock for a test; set changes the time.
func fakeClock(t *testing.T, start time.Time) (set func(time.Time)) {
	t.Helper()
	current := start
	previous := now
	now = func() time.Time { return current }
	t.Cleanup(func() { now = previous })
	return func(next time.Time) { current = next }
}

func logNames(t *testing.T, dir string) []string {
	t.Helper()
	entries, err := os.ReadDir(dir)
	if err != nil {
		t.Fatal(err)
	}
	var names []string
	for _, entry := range entries {
		names = append(names, entry.Name())
	}
	sort.Strings(names)
	return names
}

func day(d int) time.Time { return time.Date(2026, 3, d, 12, 0, 0, 0, time.Local) }

func TestDailyLogFiles(t *testing.T) {
	set := fakeClock(t, day(1))
	dir := filepath.Join(t.TempDir(), "logs")
	f, err := openDailyFile(dir)
	if err != nil {
		t.Fatal(err)
	}
	defer f.Close()
	if _, err := f.Write([]byte("first day\n")); err != nil {
		t.Fatal(err)
	}
	set(day(2).Add(-11*time.Hour - time.Minute)) // 00:59 on the second day
	if _, err := f.Write([]byte("second day\n")); err != nil {
		t.Fatal(err)
	}
	if got := strings.Join(logNames(t, dir), " "); got != "arman-vpn-2026-03-01.log arman-vpn-2026-03-02.log" {
		t.Fatalf("files = %s", got)
	}
	data, _ := os.ReadFile(DayFile(dir, day(2)))
	if string(data) != "second day\n" {
		t.Fatalf("second day file = %q", data)
	}
}

// A week of files is kept; when the eighth day starts the oldest file is
// deleted. Log files of older versions go, other files stay.
func TestLogsKeptForOneWeek(t *testing.T) {
	set := fakeClock(t, day(10))
	dir := filepath.Join(t.TempDir(), "logs")
	if err := os.MkdirAll(dir, 0o700); err != nil {
		t.Fatal(err)
	}
	for _, name := range []string{"arman-vpn.log", "arman-vpn.log.3", "notes.txt"} {
		if err := os.WriteFile(filepath.Join(dir, name), []byte("x"), 0o600); err != nil {
			t.Fatal(err)
		}
	}
	for d := 1; d <= 9; d++ {
		if err := os.WriteFile(DayFile(dir, day(d)), []byte("x"), 0o600); err != nil {
			t.Fatal(err)
		}
	}
	f, err := openDailyFile(dir)
	if err != nil {
		t.Fatal(err)
	}
	defer f.Close()
	want := []string{"arman-vpn-2026-03-04.log", "arman-vpn-2026-03-05.log", "arman-vpn-2026-03-06.log", "arman-vpn-2026-03-07.log",
		"arman-vpn-2026-03-08.log", "arman-vpn-2026-03-09.log", "arman-vpn-2026-03-10.log", "notes.txt"}
	if got := logNames(t, dir); strings.Join(got, " ") != strings.Join(want, " ") {
		t.Fatalf("files = %v", got)
	}

	set(day(11))
	if _, err := f.Write([]byte("next day\n")); err != nil {
		t.Fatal(err)
	}
	got := logNames(t, dir)
	if len(got) != 8 || got[0] != "arman-vpn-2026-03-05.log" || got[6] != "arman-vpn-2026-03-11.log" {
		t.Fatalf("after the eighth day started: %v", got)
	}
}

// Two processes (the service and a tray or status screen) append to the
// same day file and both move to the next day's file.
func TestDailyFileSharedByTwoWriters(t *testing.T) {
	set := fakeClock(t, day(1))
	dir := filepath.Join(t.TempDir(), "logs")
	a, err := openDailyFile(dir)
	if err != nil {
		t.Fatal(err)
	}
	defer a.Close()
	b, err := openDailyFile(dir)
	if err != nil {
		t.Fatal(err)
	}
	defer b.Close()
	for i, w := range []*dailyFile{a, b, a, b} {
		if i == 2 {
			set(day(2))
		}
		if _, err := w.Write([]byte("line\n")); err != nil {
			t.Fatal(err)
		}
	}
	for _, d := range []int{1, 2} {
		data, err := os.ReadFile(DayFile(dir, day(d)))
		if err != nil || string(data) != "line\nline\n" {
			t.Fatalf("day %d: %q %v", d, data, err)
		}
	}
}

func TestDailyLogSizeLimit(t *testing.T) {
	set := fakeClock(t, day(1))
	previous := maxDayBytes
	maxDayBytes = 1000
	t.Cleanup(func() { maxDayBytes = previous })
	dir := filepath.Join(t.TempDir(), "logs")
	f, err := openDailyFile(dir)
	if err != nil {
		t.Fatal(err)
	}
	defer f.Close()
	line := append(bytes.Repeat([]byte("x"), 99), '\n')
	for i := 0; i < 50; i++ {
		if _, err := f.Write(line); err != nil {
			t.Fatal(err)
		}
	}
	data, _ := os.ReadFile(DayFile(dir, day(1)))
	if len(data) > 1200 || strings.Count(string(data), "lines are dropped until tomorrow") != 1 {
		t.Fatalf("day file holds %d bytes: %q", len(data), data[len(data)-100:])
	}
	set(day(2))
	if _, err := f.Write(line); err != nil {
		t.Fatal(err)
	}
	if data, _ := os.ReadFile(DayFile(dir, day(2))); !bytes.Equal(data, line) {
		t.Fatalf("the next day starts a new file: %q", data)
	}
}

func TestDefaultLogLimits(t *testing.T) {
	if keepLogDays != 7 || int64(keepLogDays)*maxDayBytes > 100<<20 {
		t.Fatalf("days %d, per day %d", keepLogDays, maxDayBytes)
	}
}

// A day file deleted while open (by hand, or by another copy) is created
// again, so the log does not go on into a file nobody can see.
func TestDeletedLogFileIsCreatedAgain(t *testing.T) {
	set := fakeClock(t, day(1))
	dir := filepath.Join(t.TempDir(), "logs")
	f, err := openDailyFile(dir)
	if err != nil {
		t.Fatal(err)
	}
	defer f.Close()
	if _, err := f.Write([]byte("before\n")); err != nil {
		t.Fatal(err)
	}
	if err := os.Remove(DayFile(dir, day(1))); err != nil {
		t.Fatalf("deleting the open file: %v", err)
	}
	set(day(1).Add(fileCheckInterval))
	if _, err := f.Write([]byte("after\n")); err != nil {
		t.Fatal(err)
	}
	data, err := os.ReadFile(DayFile(dir, day(1)))
	if err != nil || string(data) != "after\n" {
		t.Fatalf("the file was not created again: %q %v", data, err)
	}
}

// Old day files go after keepLogDays days, also those named before 1.0.9
// (firefox-vpn-<day>.log); other files stay.
func TestOldDayFilesAreRemovedUnderEitherName(t *testing.T) {
	dir := t.TempDir()
	today := time.Date(2026, 11, 4, 12, 0, 0, 0, time.Local)
	files := map[string]bool{
		"arman-vpn-2026-11-04.log":   true,
		"arman-vpn-2026-10-01.log":   false,
		"firefox-vpn-2026-11-03.log": true,
		"firefox-vpn-2026-10-01.log": false,
		"notes.txt":                  true,
	}
	for name := range files {
		os.WriteFile(filepath.Join(dir, name), []byte("x"), 0o600)
	}
	pruneLogs(dir, today)
	for name, kept := range files {
		_, err := os.Stat(filepath.Join(dir, name))
		if (err == nil) != kept {
			t.Errorf("%s: kept=%v, want %v", name, err == nil, kept)
		}
	}
}
