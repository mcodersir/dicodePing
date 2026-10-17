//go:build !windows

package main

import "syscall"

func interfaceControl(name string) func(string, string, syscall.RawConn) error { return nil }
