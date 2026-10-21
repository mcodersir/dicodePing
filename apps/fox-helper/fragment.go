package main

// The split strategy follows FoxyVPN v1.0.7 (MIT); TLS still verifies the
// original hostname and certificate. Only the first ClientHello is split.
import (
	"encoding/binary"
	"io"
	"net"
	"sync"
	"time"
)

type helloSplitConn struct {
	net.Conn
	mode string
	once sync.Once
}

func sniStart(b []byte) int {
	if len(b) < 44 || b[0] != 22 || b[5] != 1 {
		return -1
	}
	p := 43
	p += 1 + int(b[p])
	if p+2 > len(b) {
		return -1
	}
	p += 2 + int(binary.BigEndian.Uint16(b[p:]))
	if p >= len(b) {
		return -1
	}
	p += 1 + int(b[p])
	if p+2 > len(b) {
		return -1
	}
	end := p + 2 + int(binary.BigEndian.Uint16(b[p:]))
	p += 2
	if end > len(b) {
		return -1
	}
	for p+4 <= end {
		kind := binary.BigEndian.Uint16(b[p:])
		n := int(binary.BigEndian.Uint16(b[p+2:]))
		p += 4
		if p+n > end {
			return -1
		}
		if kind == 0 && n >= 5 && b[p+2] == 0 {
			l := int(binary.BigEndian.Uint16(b[p+3:]))
			if l > 0 && l+5 <= n {
				return p + 5
			}
		}
		p += n
	}
	return -1
}
func (c *helloSplitConn) Write(b []byte) (int, error) {
	first := false
	c.once.Do(func() { first = true })
	if !first || c.mode == "off" || len(b) < 6 || b[0] != 22 || b[5] != 1 {
		return c.Conn.Write(b)
	}
	cut := 1
	if c.mode != "first_byte" {
		if n := sniStart(b); n > 0 && n < len(b)-1 {
			cut = n
		}
	}
	written := 0
	for _, part := range [][]byte{b[:cut], b[cut : cut+1], b[cut+1:]} {
		if len(part) == 0 {
			continue
		}
		n, err := c.Conn.Write(part)
		written += n
		if err != nil {
			return written, err
		}
		if n != len(part) {
			return written, io.ErrShortWrite
		}
		if written < len(b) {
			time.Sleep(5 * time.Millisecond)
		}
	}
	return written, nil
}
