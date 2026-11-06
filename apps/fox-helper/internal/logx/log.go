package logx

import (
	"errors"
	"fmt"
	"io"
	"net"
	"os"
	"strings"
	"sync"
	"sync/atomic"
	"time"
)

var (
	// Verbose enables CONNECT destinations and debug lines; the dashboard
	// can change it at runtime.
	Verbose   atomic.Bool
	logMu     sync.Mutex
	logOutput io.Writer = os.Stderr
)

// SetOutput changes where log lines are written; the dashboard's log
// view is unaffected.
func SetOutput(w io.Writer) {
	logMu.Lock()
	logOutput = w
	logMu.Unlock()
}

func logEvent(level, format string, args ...any) {
	message := fmt.Sprintf(format, args...)
	now := time.Now()
	logMu.Lock()
	fmt.Fprintf(logOutput, "%s %-5s %s\n", now.Format(time.RFC3339), level, message)
	logMu.Unlock()
	Logs.add(now, level, message)
}

func Debug(format string, args ...any) {
	if !Verbose.Load() {
		return
	}
	logEvent("DEBUG", format, args...)
}

func Info(format string, args ...any) {
	logEvent("INFO", format, args...)
}

func Warn(format string, args ...any) {
	logEvent("WARN", format, args...)
}

func Error(format string, args ...any) {
	logEvent("ERROR", format, args...)
}

// Email is an account's email (or its label) for a log line: with the
// name hidden but for its first letters, ha****@example.com, unless the log
// is verbose (Detailed logs), so logs people share do not carry it. A label
// that is no email address is shown as it is.
func Email(name string) string {
	at := strings.IndexByte(name, '@')
	if Verbose.Load() || at < 0 {
		return name
	}
	local, domain := name[:at], name[at:]
	shown := 2
	switch {
	case len(local) == 0:
		shown = 0
	case len(local) < 4:
		shown = 1
	}
	return local[:shown] + "****" + domain
}

func Target(target string) string {
	if Verbose.Load() {
		return target
	}
	return "<redacted; use -verbose>"
}

func Err(err error) string {
	if err == nil {
		return "<nil>"
	}
	if Verbose.Load() {
		return err.Error()
	}
	var r redacter
	if errors.As(err, &r) {
		return r.Redacted()
	}
	return err.Error()
}

// redacter is an error that can describe itself without sensitive details,
// for logs that are not verbose.
type redacter interface {
	error
	Redacted() string
}

func Addr(addr net.Addr) string {
	if addr == nil {
		return "<unknown>"
	}
	return addr.String()
}
