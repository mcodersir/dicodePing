//go:build !windows && !linux

package netstate

func connected() bool { return true }

func current() (string, bool) { return "", false }
