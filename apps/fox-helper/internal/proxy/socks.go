package proxy

import (
	"bufio"
	"crypto/subtle"
	"encoding/binary"
	"errors"
	"fmt"
	"io"
	"net"
	"time"

	"dicodeping/fox/internal/logx"
)

const (
	socksVersion5       = 0x05
	socksCmdConnect     = 0x01
	socksAtypIPv4       = 0x01
	socksAtypDomain     = 0x03
	socksAtypIPv6       = 0x04
	socksAuthNoAuth     = 0x00
	socksAuthUserPass   = 0x02
	socksUserPassVer    = 0x01
	socksAuthNoAccept   = 0xff
	socksReplySuccess   = 0x00
	socksReplyFailure   = 0x01
	socksReplyNotAllow  = 0x02
	socksReplyNetUnrch  = 0x03
	socksReplyHostUnrch = 0x04
	socksReplyCmdUnsup  = 0x07
	socksReplyAtypUnsup = 0x08
)

type SOCKSServer struct {
	// Auth, when set, requires username/password authentication.
	Auth *socksCredentials
	// Notices, when set, collects requests refused because of a limit, for
	// the dashboard.
	Notices *Notices
	// Allow, when set, refuses at once a target (host, port) it rejects,
	// without trying it: the TUN mode's rule for the ports Mozilla's proxy
	// does not carry.
	Allow func(host, port string) bool
	// AllowUDP, when set, does the same for UDP: a destination it rejects gets
	// no tunnel, and its packets are dropped.
	AllowUDP func(host, port string) bool
	// Conns, when set, lists the connections (the dashboard's Connections),
	// as Inbound: "tun", or by the client's protocol (socks5, http) when
	// empty. Transport tells h2 or h3 for a connection through Mozilla.
	Conns            *Connections
	Inbound          string
	Transport        func() string
	upstream         tunnelOpener
	handshakeTimeout time.Duration
	idleTimeout      time.Duration
	connSlots        chan struct{}
}

func NewSOCKSServer(upstream tunnelOpener, handshakeTimeout, idleTimeout time.Duration, maxConns int) *SOCKSServer {
	var slots chan struct{}
	if maxConns > 0 {
		slots = make(chan struct{}, maxConns)
	}
	return &SOCKSServer{
		upstream:         upstream,
		handshakeTimeout: handshakeTimeout,
		idleTimeout:      idleTimeout,
		connSlots:        slots,
	}
}

func (s *SOCKSServer) acquireConnSlot() bool {
	if s.connSlots == nil {
		return true
	}
	select {
	case s.connSlots <- struct{}{}:
		return true
	default:
		return false
	}
}

func (s *SOCKSServer) releaseConnSlot() {
	if s.connSlots == nil {
		return
	}
	<-s.connSlots
}

func (s *SOCKSServer) handleConn(conn net.Conn) {
	start := time.Now()
	clientAddr := logx.Addr(conn.RemoteAddr())
	if !s.acquireConnSlot() {
		logx.Warn("client rejected: connection limit reached client=%s", clientAddr)
		_ = conn.Close()
		return
	}
	defer s.releaseConnSlot()
	defer conn.Close()
	logx.Debug("client connected client=%s", clientAddr)

	if s.handshakeTimeout > 0 {
		_ = conn.SetDeadline(time.Now().Add(s.handshakeTimeout))
	}
	// SOCKS5 starts with its version byte; anything else is an HTTP proxy
	// request on the same port.
	reader := bufio.NewReader(conn)
	first, err := reader.Peek(1)
	if err != nil {
		return
	}
	client := &bufferedConn{Conn: conn, r: reader}
	if first[0] != socksVersion5 {
		s.serveHTTP(client, clientAddr, start)
		return
	}
	command, target, replyCode, err := handshakeSOCKS5Request(client, s.Auth)
	if err == nil && command == socksCmdUDP {
		if s.handshakeTimeout > 0 {
			_ = conn.SetDeadline(time.Time{})
		}
		s.serveUDPAssociate(client, conn, clientAddr)
		return
	}
	if err != nil {
		var cmdErr *unsupportedCommandError
		switch {
		case errors.Is(err, errSOCKSAuth):
			logx.Warn("SOCKS5 client rejected: %s client=%s", err, clientAddr)
		case errors.As(err, &cmdErr):
			s.Notices.record(NoticeCommand, cmdErr.name(), "")
			logx.Warn("SOCKS5 client asked for %s, which this proxy does not support client=%s", cmdErr.name(), clientAddr)
		default:
			logx.Debug("SOCKS5 handshake failed client=%s reply=%d err=%v", clientAddr, replyCode, err)
		}
		if replyCode != 0 {
			if writeErr := writeSOCKSReply(conn, replyCode, nil); writeErr != nil {
				logx.Debug("SOCKS5 handshake failure reply failed client=%s reply=%d err=%v", clientAddr, replyCode, writeErr)
			}
		}
		return
	}
	if s.handshakeTimeout > 0 {
		_ = conn.SetDeadline(time.Time{})
	}
	logx.Debug("SOCKS5 CONNECT requested client=%s target=%s", clientAddr, logx.Target(target))
	if s.Allow != nil {
		if host, port, err := net.SplitHostPort(target); err != nil || !s.Allow(host, port) {
			logx.Debug("SOCKS5 CONNECT refused at once: the VPN does not carry it client=%s target=%s", clientAddr, logx.Target(target))
			s.Conns.refused(s.inbound("socks5"), clientAddr, target, RoutePort)
			_ = writeSOCKSReply(conn, socksReplyNotAllow, nil)
			return
		}
	}

	upstreamConn, err := s.openTarget(conn, target, clientAddr, s.inbound("socks5"))
	if err != nil {
		reply := mapUpstreamError(err)
		if portRefused(target, err) {
			reply = socksReplyNotAllow
		}
		if writeErr := writeSOCKSReply(conn, reply, nil); writeErr != nil {
			logx.Debug("SOCKS5 upstream failure reply failed client=%s target=%s reply=%d err=%v", clientAddr, logx.Target(target), reply, writeErr)
		}
		return
	}
	defer upstreamConn.Close()

	if err := writeSOCKSReply(conn, socksReplySuccess, conn.LocalAddr()); err != nil {
		logx.Debug("SOCKS5 success reply failed client=%s target=%s err=%v", clientAddr, logx.Target(target), err)
		return
	}

	proxyBidirectional(client, upstreamConn, s.idleTimeout)
	logx.Debug("client disconnected client=%s target=%s duration=%s", clientAddr, logx.Target(target), time.Since(start).Round(time.Millisecond))
}

// inbound is how a client came, for the list of connections: the server's
// Inbound, else protocol.
func (s *SOCKSServer) inbound(protocol string) string {
	if s.Inbound != "" {
		return s.Inbound
	}
	return protocol
}

func clientAffinityKey(addr net.Addr) string {
	if addr == nil {
		return ""
	}
	if tcpAddr, ok := addr.(*net.TCPAddr); ok && tcpAddr.IP != nil {
		return tcpAddr.IP.String()
	}
	if host, _, err := net.SplitHostPort(addr.String()); err == nil {
		return host
	}
	return addr.String()
}

// socksCredentials is the username and password clients must present.
type socksCredentials struct{ username, password string }

func SOCKSCredentials(username, password string) *socksCredentials {
	if username == "" {
		return nil
	}
	return &socksCredentials{username: username, password: password}
}

// errSOCKSAuth reports a client that did not authenticate.
var errSOCKSAuth = errors.New("SOCKS5 authentication failed")

func handshakeSOCKS5(conn net.Conn) (string, byte, error) {
	return handshakeSOCKS5Auth(conn, nil)
}

// handshakeSOCKS5Auth negotiates the method and reads a CONNECT request;
// anything else is an unsupported command.
func handshakeSOCKS5Auth(conn net.Conn, auth *socksCredentials) (string, byte, error) {
	command, target, reply, err := handshakeSOCKS5Request(conn, auth)
	if err == nil && command != socksCmdConnect {
		return "", socksReplyCmdUnsup, &unsupportedCommandError{cmd: command}
	}
	return target, reply, err
}

// handshakeSOCKS5Request negotiates the method (no authentication, or
// username/password when auth is set), then reads the request: CONNECT, with
// its target, or UDP ASSOCIATE, whose address is ignored (the client's first
// packet says where it sends from).
func handshakeSOCKS5Request(conn net.Conn, auth *socksCredentials) (byte, string, byte, error) {
	header := make([]byte, 2)
	if _, err := io.ReadFull(conn, header); err != nil {
		return 0, "", 0, err
	}
	if header[0] != socksVersion5 {
		return 0, "", 0, fmt.Errorf("unexpected SOCKS version %d", header[0])
	}

	methods := make([]byte, int(header[1]))
	if _, err := io.ReadFull(conn, methods); err != nil {
		return 0, "", 0, err
	}

	wanted := byte(socksAuthNoAuth)
	if auth != nil {
		wanted = socksAuthUserPass
	}
	method := byte(socksAuthNoAccept)
	for _, candidate := range methods {
		if candidate == wanted {
			method = wanted
			break
		}
	}
	if _, err := conn.Write([]byte{socksVersion5, method}); err != nil {
		return 0, "", 0, err
	}
	if method == socksAuthNoAccept {
		if auth != nil {
			return 0, "", 0, fmt.Errorf("%w: the client does not offer username/password", errSOCKSAuth)
		}
		return 0, "", 0, fmt.Errorf("no supported SOCKS auth methods")
	}
	if method == socksAuthUserPass {
		if err := checkSOCKSUserPass(conn, auth); err != nil {
			return 0, "", 0, err
		}
	}

	reqHeader := make([]byte, 4)
	if _, err := io.ReadFull(conn, reqHeader); err != nil {
		return 0, "", 0, err
	}
	if reqHeader[0] != socksVersion5 {
		return 0, "", socksReplyFailure, fmt.Errorf("unexpected request version %d", reqHeader[0])
	}
	if reqHeader[1] != socksCmdConnect && reqHeader[1] != socksCmdUDP {
		return 0, "", socksReplyCmdUnsup, &unsupportedCommandError{cmd: reqHeader[1]}
	}

	host, err := readSOCKSAddr(conn, reqHeader[3])
	if err != nil {
		if errors.Is(err, errUnsupportedAddrType) {
			return 0, "", socksReplyAtypUnsup, err
		}
		return 0, "", socksReplyFailure, err
	}

	portBytes := make([]byte, 2)
	if _, err := io.ReadFull(conn, portBytes); err != nil {
		return 0, "", socksReplyFailure, err
	}
	port := binary.BigEndian.Uint16(portBytes)
	return reqHeader[1], net.JoinHostPort(host, fmt.Sprintf("%d", port)), socksReplySuccess, nil
}

// checkSOCKSUserPass runs the RFC 1929 sub-negotiation.
func checkSOCKSUserPass(conn net.Conn, auth *socksCredentials) error {
	header := make([]byte, 2)
	if _, err := io.ReadFull(conn, header); err != nil {
		return err
	}
	if header[0] != socksUserPassVer {
		return fmt.Errorf("%w: unexpected sub-negotiation version %d", errSOCKSAuth, header[0])
	}
	username := make([]byte, int(header[1]))
	if _, err := io.ReadFull(conn, username); err != nil {
		return err
	}
	plen := make([]byte, 1)
	if _, err := io.ReadFull(conn, plen); err != nil {
		return err
	}
	password := make([]byte, int(plen[0]))
	if _, err := io.ReadFull(conn, password); err != nil {
		return err
	}
	userOK := subtle.ConstantTimeCompare(username, []byte(auth.username)) == 1
	passOK := subtle.ConstantTimeCompare(password, []byte(auth.password)) == 1
	if !userOK || !passOK {
		_, _ = conn.Write([]byte{socksUserPassVer, 0x01})
		return fmt.Errorf("%w: wrong username or password", errSOCKSAuth)
	}
	_, err := conn.Write([]byte{socksUserPassVer, 0x00})
	return err
}

var errUnsupportedAddrType = errors.New("unsupported SOCKS address type")

// unsupportedCommandError is a SOCKS command other than CONNECT.
type unsupportedCommandError struct{ cmd byte }

func (e *unsupportedCommandError) Error() string {
	return fmt.Sprintf("unsupported SOCKS command %d (%s)", e.cmd, e.name())
}

func (e *unsupportedCommandError) name() string {
	switch e.cmd {
	case 0x02:
		return "BIND"
	case 0x03:
		return "UDP"
	}
	return fmt.Sprintf("command %d", e.cmd)
}

func readSOCKSAddr(r io.Reader, atyp byte) (string, error) {
	switch atyp {
	case socksAtypIPv4:
		buf := make([]byte, net.IPv4len)
		if _, err := io.ReadFull(r, buf); err != nil {
			return "", err
		}
		return net.IP(buf).String(), nil
	case socksAtypIPv6:
		buf := make([]byte, net.IPv6len)
		if _, err := io.ReadFull(r, buf); err != nil {
			return "", err
		}
		return net.IP(buf).String(), nil
	case socksAtypDomain:
		var size [1]byte
		if _, err := io.ReadFull(r, size[:]); err != nil {
			return "", err
		}
		buf := make([]byte, int(size[0]))
		if _, err := io.ReadFull(r, buf); err != nil {
			return "", err
		}
		return string(buf), nil
	default:
		return "", errUnsupportedAddrType
	}
}

func writeSOCKSReply(w io.Writer, rep byte, addr net.Addr) error {
	host := "0.0.0.0"
	port := 0
	switch a := addr.(type) {
	case *net.TCPAddr:
		host, port = a.IP.String(), a.Port
	case *net.UDPAddr:
		host, port = a.IP.String(), a.Port
	}

	ip := net.ParseIP(host)
	atyp := byte(socksAtypIPv4)
	addrBytes := []byte{0, 0, 0, 0}
	if ip != nil && ip.To4() != nil {
		addrBytes = ip.To4()
	} else if ip != nil && ip.To16() != nil {
		atyp = socksAtypIPv6
		addrBytes = ip.To16()
	}

	reply := make([]byte, 0, 6+len(addrBytes))
	reply = append(reply, socksVersion5, rep, 0x00, atyp)
	reply = append(reply, addrBytes...)
	reply = append(reply, byte(port>>8), byte(port))
	_, err := w.Write(reply)
	return err
}

func mapUpstreamError(err error) byte {
	if errors.Is(err, ErrBlockedByRule) {
		return socksReplyNotAllow
	}
	if errors.Is(err, ErrNoUsableSession) {
		return socksReplyHostUnrch
	}
	if errors.Is(err, errUnsupportedAddrType) {
		return socksReplyAtypUnsup
	}
	var netErr net.Error
	if errors.As(err, &netErr) && netErr.Timeout() {
		return socksReplyHostUnrch
	}
	return socksReplyFailure
}

// ServeConn serves one client, as ServeSOCKS serves each it accepts.
func (s *SOCKSServer) ServeConn(conn net.Conn) { s.handleConn(conn) }

// ServeSOCKS accepts clients until the listener is closed, backing off on
// transient accept errors.
func ServeSOCKS(ln net.Listener, server *SOCKSServer) {
	var acceptRetryDelay time.Duration
	for {
		conn, err := ln.Accept()
		if err != nil {
			if errors.Is(err, net.ErrClosed) {
				return
			}
			if acceptRetryDelay == 0 {
				acceptRetryDelay = 5 * time.Millisecond
			} else {
				acceptRetryDelay *= 2
			}
			if acceptRetryDelay > time.Second {
				acceptRetryDelay = time.Second
			}
			logx.Warn("accept failed; retrying delay=%s err=%v", acceptRetryDelay, err)
			time.Sleep(acceptRetryDelay)
			continue
		}
		acceptRetryDelay = 0
		go server.handleConn(conn)
	}
}
