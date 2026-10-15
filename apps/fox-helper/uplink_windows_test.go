package main

import (
	"net"
	"syscall"
	"testing"
)

type socketControl struct{ fd syscall.Handle }

func (s socketControl) Control(f func(uintptr)) error    { f(uintptr(s.fd)); return nil }
func (s socketControl) Read(f func(uintptr) bool) error  { panic("unused") }
func (s socketControl) Write(f func(uintptr) bool) error { panic("unused") }

func TestWindowsSocketPinsTheRequestedAdapter(t *testing.T) {
	interfaces, err := net.Interfaces()
	if err != nil {
		t.Fatal(err)
	}
	var nic net.Interface
	for _, candidate := range interfaces {
		if candidate.Flags&net.FlagUp != 0 {
			nic = candidate
			break
		}
	}
	if nic.Index == 0 {
		t.Fatal("No active adapter on Windows runner")
	}
	for _, v6 := range []bool{false, true} {
		family, level, network, expected := syscall.AF_INET, syscall.IPPROTO_IP, "tcp4", nic.Index
		if v6 {
			family, level, network, expected = syscall.AF_INET6, syscall.IPPROTO_IPV6, "tcp6", nic.Index
		}
		socket, err := syscall.Socket(family, syscall.SOCK_STREAM, syscall.IPPROTO_TCP)
		if err != nil {
			t.Fatal(err)
		}
		err = interfaceControl(nic.Name)(network, "", socketControl{socket})
		if err != nil {
			syscall.Closesocket(socket)
			t.Fatal(err)
		}
		actual, err := syscall.GetsockoptInt(socket, level, 31)
		syscall.Closesocket(socket)
		if err != nil || actual != expected {
			t.Fatalf("%s adapter binding: got %d want %d: %v", network, actual, expected, err)
		}
	}
}
