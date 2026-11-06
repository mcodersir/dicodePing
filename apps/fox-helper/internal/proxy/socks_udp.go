package proxy

import (
	"encoding/binary"
	"errors"
	"io"
	"net"
	"net/netip"
	"strconv"
	"sync"
	"sync/atomic"
	"time"

	"dicodeping/fox/internal/logx"
)

// SOCKS5 UDP ASSOCIATE (RFC 1928 7): a client asks over its TCP connection,
// gets the address of a UDP socket, and sends it packets that name their
// destination. Each destination is a flow with a tunnel of its own, opened
// with its first packet. The association ends with the TCP connection.

const (
	socksCmdUDP = 0x03

	// udpFlowIdle closes a destination without packets for this long.
	udpFlowIdle = 2 * time.Minute
	// udpFlowCheck spaces the looks for idle flows.
	udpFlowCheck = 15 * time.Second
	// udpMaxFlows bounds one association's destinations; the one unused for
	// longest makes room for a new one.
	udpMaxFlows = 128
	// udpPending is how many packets wait for a tunnel being opened.
	udpPending = 16
	// udpMaxPacket is the largest UDP packet.
	udpMaxPacket = 65535
	// udpRetryWait is how long a destination's packets are dropped after its
	// tunnel failed, and udpRefusedWait after it was refused, before the next
	// packet tries again.
	udpRetryWait   = 2 * time.Second
	udpRefusedWait = 30 * time.Second
)

// udpAssociation is one client's UDP socket here.
type udpAssociation struct {
	s      *SOCKSServer
	opener udpTunnelOpener
	sock   *net.UDPConn
	// conn is the client's TCP connection, whose end ends the association.
	conn net.Conn
	// client is the address the packets must come from; the first packet
	// fixes the port.
	client     netip.Addr
	clientAddr string
	clientKey  string
	inbound    string

	mu     sync.Mutex
	peer   netip.AddrPort
	flows  map[string]*udpFlow
	closed bool
}

// serveUDPAssociate serves a client's UDP ASSOCIATE until its TCP connection
// (conn, read through client) ends.
func (s *SOCKSServer) serveUDPAssociate(client io.Reader, conn net.Conn, clientAddr string) {
	opener, ok := s.upstream.(udpTunnelOpener)
	remote, remoteOK := addrOf(conn.RemoteAddr())
	local, localOK := addrOf(conn.LocalAddr())
	if !ok || !remoteOK || !localOK {
		s.Notices.record(NoticeCommand, "UDP", "")
		_ = writeSOCKSReply(conn, socksReplyCmdUnsup, nil)
		return
	}
	sock, err := net.ListenUDP("udp", &net.UDPAddr{IP: local.AsSlice()})
	if err != nil {
		logx.Warn("opening a UDP socket for a SOCKS5 client failed client=%s err=%s", clientAddr, logx.Err(err))
		_ = writeSOCKSReply(conn, socksReplyFailure, nil)
		return
	}
	defer sock.Close()
	if err := writeSOCKSReply(conn, socksReplySuccess, sock.LocalAddr()); err != nil {
		return
	}
	logx.Debug("SOCKS5 UDP ASSOCIATE client=%s relay=%s", clientAddr, sock.LocalAddr())
	a := &udpAssociation{
		s:          s,
		opener:     opener,
		sock:       sock,
		conn:       conn,
		client:     remote,
		clientAddr: clientAddr,
		clientKey:  clientAffinityKey(conn.RemoteAddr()),
		inbound:    s.inbound("socks5"),
		flows:      map[string]*udpFlow{},
	}
	defer a.close()
	go func() {
		// The association lasts as long as this connection.
		_, _ = io.Copy(io.Discard, client)
		_ = sock.Close()
	}()
	go a.closeIdle()
	a.readClient()
}

// addrOf is the IP address of a TCP address.
func addrOf(addr net.Addr) (netip.Addr, bool) {
	tcp, ok := addr.(*net.TCPAddr)
	if !ok {
		return netip.Addr{}, false
	}
	ip, ok := netip.AddrFromSlice(tcp.IP)
	return ip.Unmap(), ok
}

// readClient takes the client's packets until the socket closes.
func (a *udpAssociation) readClient() {
	buf := make([]byte, udpMaxPacket+1)
	for {
		n, from, err := a.sock.ReadFromUDPAddrPort(buf)
		if err != nil {
			if errors.Is(err, net.ErrClosed) {
				return
			}
			// On Windows an ICMP unreachable for an earlier reply surfaces
			// as a read error; the socket goes on.
			logx.Debug("SOCKS5 UDP read err=%s", logx.Err(err))
			if a.isClosed() {
				return
			}
			continue
		}
		from = netip.AddrPortFrom(from.Addr().Unmap(), from.Port())
		if from.Addr() != a.client {
			continue
		}
		target, payload, ok := parseUDPRequest(buf[:n])
		if !ok {
			continue
		}
		a.mu.Lock()
		if !a.peer.IsValid() {
			a.peer = from
		}
		sameClient := a.peer == from
		a.mu.Unlock()
		if !sameClient {
			continue
		}
		a.flow(target).send(payload)
	}
}

func (a *udpAssociation) isClosed() bool {
	a.mu.Lock()
	defer a.mu.Unlock()
	return a.closed
}

// flow returns target's flow, making room for it when there are too many.
func (a *udpAssociation) flow(target string) *udpFlow {
	a.mu.Lock()
	defer a.mu.Unlock()
	if f, ok := a.flows[target]; ok {
		return f
	}
	if len(a.flows) >= udpMaxFlows {
		var oldest *udpFlow
		for _, f := range a.flows {
			if oldest == nil || f.lastUsed.Load() < oldest.lastUsed.Load() {
				oldest = f
			}
		}
		delete(a.flows, oldest.target)
		go oldest.close()
	}
	f := &udpFlow{a: a, target: target, header: udpReplyHeader(target)}
	f.lastUsed.Store(time.Now().UnixNano())
	a.flows[target] = f
	return f
}

// closeIdle closes the flows without packets, until the association ends.
func (a *udpAssociation) closeIdle() {
	ticker := time.NewTicker(udpFlowCheck)
	defer ticker.Stop()
	for range ticker.C {
		a.mu.Lock()
		if a.closed {
			a.mu.Unlock()
			return
		}
		for target, f := range a.flows {
			if time.Since(time.Unix(0, f.lastUsed.Load())) > udpFlowIdle {
				delete(a.flows, target)
				go f.close()
			}
		}
		a.mu.Unlock()
	}
}

func (a *udpAssociation) close() {
	a.mu.Lock()
	a.closed = true
	flows := a.flows
	a.flows = map[string]*udpFlow{}
	a.mu.Unlock()
	for _, f := range flows {
		f.close()
	}
	logx.Debug("SOCKS5 UDP association ended client=%s", a.clientAddr)
}

// udpFlow is a client's packets to one destination.
type udpFlow struct {
	a      *udpAssociation
	target string
	// header starts each reply to the client.
	header   []byte
	lastUsed atomic.Int64

	mu      sync.Mutex
	tunnel  UDPTunnel
	opening bool
	closed  bool
	pending [][]byte
	// waitUntil: packets are dropped until then, after a failure.
	waitUntil time.Time
	tracked   *trackedConn
}

// send passes the client's packet on, or keeps it for a tunnel being opened.
func (f *udpFlow) send(p []byte) {
	f.lastUsed.Store(time.Now().UnixNano())
	f.mu.Lock()
	switch {
	case f.closed:
		f.mu.Unlock()
	case f.tunnel != nil:
		tunnel, tracked := f.tunnel, f.tracked
		f.mu.Unlock()
		tracked.addUp(len(p))
		if err := tunnel.WritePacket(p); err != nil {
			f.tunnelEnded(tunnel, err)
		}
	case f.opening:
		if len(f.pending) < udpPending {
			f.pending = append(f.pending, append([]byte(nil), p...))
		}
		f.mu.Unlock()
	case time.Now().Before(f.waitUntil):
		f.mu.Unlock()
	default:
		f.opening = true
		f.pending = append(f.pending[:0], append([]byte(nil), p...))
		f.mu.Unlock()
		go f.open()
	}
}

// open opens the tunnel, sends what waited, and reads the replies.
func (f *udpFlow) open() {
	a := f.a
	if allow := a.s.AllowUDP; allow != nil {
		if host, port, err := net.SplitHostPort(f.target); err != nil || !allow(host, port) {
			f.mu.Lock()
			f.opening = false
			f.pending = nil
			f.waitUntil = time.Now().Add(udpRefusedWait)
			f.mu.Unlock()
			a.s.Conns.refusedUDP(a.inbound, a.clientAddr, f.target, RoutePort)
			logx.Debug("UDP refused at once: the VPN does not carry it client=%s target=%s", a.clientAddr, logx.Target(f.target))
			return
		}
	}
	tracked := a.s.Conns.beginUDP(a.inbound, a.clientAddr, f.target)
	tunnel, err := a.opener.OpenUDP(f.target, a.clientKey)
	f.mu.Lock()
	f.opening = false
	pending := f.pending
	f.pending = nil
	if errors.Is(err, errUDPEngineStopped) {
		f.mu.Unlock()
		a.s.Conns.failed(tracked, f.target, err)
		// The client's next packet goes to a new association, on the running
		// engine.
		_ = a.conn.Close()
		return
	}
	if err != nil {
		wait := udpRetryWait
		var connectErr *proxyConnectHTTPError
		if errors.Is(err, ErrUDPPort) || errors.Is(err, ErrBlockedByRule) || (errors.As(err, &connectErr) && connectErr.statusCode == 502) {
			wait = udpRefusedWait
		}
		f.waitUntil = time.Now().Add(wait)
		f.mu.Unlock()
		a.s.Conns.failed(tracked, f.target, err)
		logx.Debug("UDP tunnel open failed client=%s target=%s err=%s", a.clientAddr, logx.Target(f.target), logx.Err(err))
		return
	}
	if f.closed {
		f.mu.Unlock()
		_ = tunnel.Close()
		a.s.Conns.end(tracked)
		return
	}
	f.tunnel, f.tracked = tunnel, tracked
	f.mu.Unlock()
	transport := ""
	if a.s.Transport != nil {
		transport = a.s.Transport()
	}
	a.s.Conns.openedUDP(tracked, tunnel, transport)
	logx.Debug("UDP tunnel opened client=%s target=%s", a.clientAddr, logx.Target(f.target))
	for _, p := range pending {
		tracked.addUp(len(p))
		if err := tunnel.WritePacket(p); err != nil {
			f.tunnelEnded(tunnel, err)
			return
		}
	}
	f.readTunnel(tunnel, tracked)
}

// readTunnel passes the replies to the client until the tunnel ends.
func (f *udpFlow) readTunnel(tunnel UDPTunnel, tracked *trackedConn) {
	a := f.a
	buf := make([]byte, len(f.header)+udpMaxPacket+1)
	copy(buf, f.header)
	for {
		n, err := tunnel.ReadPacket(buf[len(f.header):])
		if err != nil {
			f.tunnelEnded(tunnel, err)
			return
		}
		f.lastUsed.Store(time.Now().UnixNano())
		tracked.addDown(n)
		a.mu.Lock()
		peer := a.peer
		a.mu.Unlock()
		if _, err := a.sock.WriteToUDPAddrPort(buf[:len(f.header)+n], peer); err != nil && errors.Is(err, net.ErrClosed) {
			f.tunnelEnded(tunnel, err)
			return
		}
	}
}

// tunnelEnded forgets a tunnel that ended; the next packet opens a new one.
func (f *udpFlow) tunnelEnded(tunnel UDPTunnel, err error) {
	f.mu.Lock()
	if f.tunnel != tunnel {
		f.mu.Unlock()
		return
	}
	f.tunnel = nil
	tracked := f.tracked
	f.tracked = nil
	if !f.closed {
		f.waitUntil = time.Now().Add(udpRetryWait)
	}
	f.mu.Unlock()
	_ = tunnel.Close()
	f.a.s.Conns.end(tracked)
	logx.Debug("UDP tunnel ended client=%s target=%s err=%s", f.a.clientAddr, logx.Target(f.target), logx.Err(err))
}

func (f *udpFlow) close() {
	f.mu.Lock()
	f.closed = true
	tunnel := f.tunnel
	tracked := f.tracked
	f.tunnel, f.tracked = nil, nil
	f.mu.Unlock()
	if tunnel != nil {
		_ = tunnel.Close()
		f.a.s.Conns.end(tracked)
	}
}

// parseUDPRequest reads a client's datagram (RFC 1928 7): its destination as
// host:port, and the packet. A fragment is dropped: fragments are optional,
// and no client sends them.
func parseUDPRequest(b []byte) (target string, payload []byte, ok bool) {
	if len(b) < 4 || b[0] != 0 || b[1] != 0 || b[2] != 0 {
		return "", nil, false
	}
	var host string
	at := 4
	switch b[3] {
	case socksAtypIPv4, socksAtypIPv6:
		size := net.IPv4len
		if b[3] == socksAtypIPv6 {
			size = net.IPv6len
		}
		if len(b) < at+size {
			return "", nil, false
		}
		ip, _ := netip.AddrFromSlice(b[at : at+size])
		host = ip.String()
		at += size
	case socksAtypDomain:
		if len(b) < at+1 || b[at] == 0 || len(b) < at+1+int(b[at]) {
			return "", nil, false
		}
		host = string(b[at+1 : at+1+int(b[at])])
		at += 1 + int(b[at])
	default:
		return "", nil, false
	}
	if len(b) < at+2 {
		return "", nil, false
	}
	port := binary.BigEndian.Uint16(b[at:])
	return net.JoinHostPort(host, strconv.Itoa(int(port))), b[at+2:], true
}

// udpReplyHeader is the header of the replies from target, which names it as
// the client did (Mozilla's proxy does not say which address a name resolved
// to).
func udpReplyHeader(target string) []byte {
	host, portText, err := net.SplitHostPort(target)
	if err != nil {
		return []byte{0, 0, 0, socksAtypIPv4, 0, 0, 0, 0, 0, 0}
	}
	port, _ := strconv.ParseUint(portText, 10, 16)
	header := []byte{0, 0, 0}
	if ip, err := netip.ParseAddr(host); err == nil {
		if ip.Is4() {
			header = append(header, socksAtypIPv4)
		} else {
			header = append(header, socksAtypIPv6)
		}
		header = append(header, ip.AsSlice()...)
	} else {
		header = append(header, socksAtypDomain, byte(len(host)))
		header = append(header, host...)
	}
	return binary.BigEndian.AppendUint16(header, uint16(port))
}
