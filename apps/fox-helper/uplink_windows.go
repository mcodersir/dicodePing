package main

import (
	"math/bits"
	"net"
	"strings"
	"syscall"
)

// IP_UNICAST_IF pins external sockets to the chosen hardware adapter, even when
// WARP installed a preferred default route. It never changes system routes.
func interfaceControl(name string) func(string, string, syscall.RawConn) error {
	if name == "" {
		return nil
	}
	return func(network, address string, raw syscall.RawConn) error {
		nic, err := net.InterfaceByName(name)
		if err != nil {
			return err
		}
		var socketErr error
		err = raw.Control(func(fd uintptr) {
			level, index := syscall.IPPROTO_IP, int(bits.ReverseBytes32(uint32(nic.Index)))
			if strings.HasSuffix(network, "6") {
				level, index = syscall.IPPROTO_IPV6, nic.Index
			}
			socketErr = syscall.SetsockoptInt(syscall.Handle(fd), level, 31, index)
		})
		if err != nil {
			return err
		}
		return socketErr
	}
}
