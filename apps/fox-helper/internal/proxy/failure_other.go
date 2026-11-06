//go:build !windows

package proxy

import "syscall"

// noNetworkErrnos are the socket errors that mean this device has no route
// to the internet.
var noNetworkErrnos = []syscall.Errno{syscall.ENETDOWN, syscall.ENETUNREACH, syscall.EHOSTUNREACH}

// cutErrnos are a connection refused, reset, or aborted.
var cutErrnos = []syscall.Errno{syscall.ECONNRESET, syscall.ECONNABORTED, syscall.ECONNREFUSED}
