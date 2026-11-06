package proxy

import (
	"bufio"
	"crypto/subtle"
	"encoding/base64"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"strings"
	"time"

	"dicodeping/fox/internal/egress"
	"dicodeping/fox/internal/logx"
)

// The SOCKS5 port also serves HTTP proxy clients (the Windows system proxy
// and applications that only know HTTP proxies): a SOCKS5 client starts
// with byte 5, an HTTP client with a request line. HTTPS goes through
// CONNECT tunnels; plain http:// requests are forwarded one per
// connection. Both use the same login, routing, and refused-port notes as
// SOCKS5.

// bufferedConn reads through the reader that peeked at the first byte, so
// nothing the client sent is lost.
type bufferedConn struct {
	net.Conn
	r *bufio.Reader
}

func (c *bufferedConn) Read(p []byte) (int, error) { return c.r.Read(p) }

// CloseWrite keeps half-close working for the relay.
func (c *bufferedConn) CloseWrite() error {
	if cw, ok := c.Conn.(interface{ CloseWrite() error }); ok {
		return cw.CloseWrite()
	}
	return nil
}

// hopHeaders are meant for the proxy, not for the destination.
var hopHeaders = []string{"Connection", "Proxy-Connection", "Keep-Alive", "Proxy-Authenticate", "Proxy-Authorization", "Te", "Trailer", "Transfer-Encoding", "Upgrade"}

func (s *SOCKSServer) serveHTTP(client *bufferedConn, clientAddr string, start time.Time) {
	req, err := http.ReadRequest(client.r)
	if err != nil {
		logx.Debug("HTTP proxy request unreadable client=%s err=%v", clientAddr, err)
		return
	}
	if s.Auth != nil && !s.Auth.matchBasic(req.Header.Get("Proxy-Authorization")) {
		logx.Warn("HTTP proxy client rejected: %s client=%s", errSOCKSAuth, clientAddr)
		writeHTTPError(client, http.StatusProxyAuthRequired, "The proxy needs the username and password set in Settings.", `Basic realm="Arman VPN"`)
		return
	}
	if s.handshakeTimeout > 0 {
		_ = client.SetDeadline(time.Time{})
	}

	if req.Method == http.MethodConnect {
		target := withDefaultPort(req.Host, "443")
		upstream, err := s.openTarget(client, target, clientAddr, s.inbound("http"))
		if err != nil {
			writeHTTPError(client, httpStatusFor(err), httpErrorText(target, err), "")
			return
		}
		defer upstream.Close()
		if _, err := io.WriteString(client, "HTTP/1.1 200 Connection established\r\n\r\n"); err != nil {
			return
		}
		proxyBidirectional(client, upstream, s.idleTimeout)
		logx.Debug("HTTP proxy client disconnected client=%s target=%s duration=%s", clientAddr, logx.Target(target), time.Since(start).Round(time.Millisecond))
		return
	}

	if req.URL == nil || !strings.EqualFold(req.URL.Scheme, "http") || req.URL.Host == "" {
		writeHTTPError(client, http.StatusBadRequest, "This is a proxy: send a CONNECT request or an absolute http:// URL.", "")
		return
	}
	target := withDefaultPort(req.URL.Host, "80")
	upstream, err := s.openTarget(client, target, clientAddr, s.inbound("http"))
	if err != nil {
		writeHTTPError(client, httpStatusFor(err), httpErrorText(target, err), "")
		return
	}
	defer upstream.Close()
	for _, h := range hopHeaders {
		req.Header.Del(h)
	}
	req.Close = true
	if err := req.Write(upstream); err != nil {
		logx.Debug("HTTP proxy request forwarding failed client=%s target=%s err=%v", clientAddr, logx.Target(target), err)
		return
	}
	resp, err := http.ReadResponse(bufio.NewReader(upstream), req)
	if err != nil {
		writeHTTPError(client, http.StatusBadGateway, "The site sent no valid answer.", "")
		return
	}
	defer resp.Body.Close()
	resp.Close = true
	_ = resp.Write(client)
}

// openTarget opens a tunnel to target for a SOCKS5 or HTTP client, lists
// it (Conns), and notes and logs a port Mozilla's proxy refuses, and a loop.
func (s *SOCKSServer) openTarget(client net.Conn, target, clientAddr, inbound string) (net.Conn, error) {
	tracked := s.Conns.begin(inbound, clientAddr, target)
	if egress.OwnDial(target) {
		if loop, warn := loops.note(target, time.Now()); loop {
			host, _, _ := net.SplitHostPort(target)
			s.Notices.record(NoticeLoop, "", host)
			if warn {
				logx.Warn("a loop: this program's own connections come back to its proxy as a client's (client=%s target=%s), so nothing connects; a program sends this program's own traffic into the proxy: in PassWall2 turn Localhost Proxy off, in another VPN program's TUN mode let arman-vpn-core connect directly", clientAddr, logx.Target(target))
			}
		}
	}
	var conn net.Conn
	var err error
	if affinityUpstream, ok := s.upstream.(clientAffinityTunnelOpener); ok {
		conn, err = affinityUpstream.OpenTunnelForClient(target, clientAffinityKey(client.RemoteAddr()))
	} else {
		conn, err = s.upstream.OpenTunnel(target)
	}
	if err == nil {
		logx.Debug("upstream tunnel open succeeded client=%s target=%s", clientAddr, logx.Target(target))
		transport := ""
		if s.Transport != nil {
			transport = s.Transport()
		}
		return s.Conns.opened(tracked, conn, transport), nil
	}
	s.Conns.failed(tracked, target, err)
	if portRefused(target, err) {
		host, port, _ := net.SplitHostPort(target)
		s.Notices.record(NoticePort, port, host)
		logx.Warn("Mozilla's proxy does not connect to port %s; it connects to ports %s only client=%s target=%s", port, UpstreamPortsText, clientAddr, logx.Target(target))
	} else {
		logx.Warn("upstream tunnel open failed client=%s target=%s err=%s", clientAddr, logx.Target(target), logx.Err(err))
	}
	return nil, err
}

func withDefaultPort(host, port string) string {
	if _, _, err := net.SplitHostPort(host); err == nil {
		return host
	}
	return net.JoinHostPort(strings.Trim(host, "[]"), port)
}

func httpStatusFor(err error) int {
	var connectErr *proxyConnectHTTPError
	switch {
	case errors.Is(err, ErrBlockedByRule):
		return http.StatusForbidden
	case errors.Is(err, ErrNoUsableSession):
		return http.StatusServiceUnavailable
	case errors.As(err, &connectErr) && connectErr.statusCode == http.StatusBadGateway:
		return http.StatusForbidden
	}
	return http.StatusBadGateway
}

func httpErrorText(target string, err error) string {
	switch {
	case portRefused(target, err):
		_, port, _ := net.SplitHostPort(target)
		return fmt.Sprintf("Mozilla's proxy does not connect to port %s; it connects to ports %s only.", port, UpstreamPortsText)
	case errors.Is(err, ErrThisMachine):
		return "The proxy does not connect to this computer itself."
	case errors.Is(err, ErrBlockedByRule):
		return "Refused by a routing rule (Settings, Routing)."
	case errors.Is(err, ErrNoUsableSession):
		return "No account can supply a connection right now; see the dashboard."
	}
	return "The connection through Mozilla's proxy failed."
}

func writeHTTPError(w io.Writer, status int, text, authenticate string) {
	body := text + "\n"
	header := fmt.Sprintf("HTTP/1.1 %d %s\r\nContent-Type: text/plain; charset=utf-8\r\nContent-Length: %d\r\nConnection: close\r\n", status, http.StatusText(status), len(body))
	if authenticate != "" {
		header += "Proxy-Authenticate: " + authenticate + "\r\n"
	}
	_, _ = io.WriteString(w, header+"\r\n"+body)
}

// matchBasic checks a Proxy-Authorization header with Basic credentials.
func (c *socksCredentials) matchBasic(header string) bool {
	scheme, encoded, ok := strings.Cut(header, " ")
	if !ok || !strings.EqualFold(scheme, "Basic") {
		return false
	}
	decoded, err := base64.StdEncoding.DecodeString(strings.TrimSpace(encoded))
	if err != nil {
		return false
	}
	user, pass, ok := strings.Cut(string(decoded), ":")
	userOK := subtle.ConstantTimeCompare([]byte(user), []byte(c.username)) == 1
	passOK := subtle.ConstantTimeCompare([]byte(pass), []byte(c.password)) == 1
	return ok && userOK && passOK
}
