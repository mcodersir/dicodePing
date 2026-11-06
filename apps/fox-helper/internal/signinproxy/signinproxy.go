// Package signinproxy is the proxy of the app's browser sign-in: an HTTP
// CONNECT proxy on loopback through which the app's browser view reaches
// Mozilla's sign-in pages. It connects the way the core's own account
// requests do (controlplane.DialContext: the configured DNS servers, every
// address of a name tried with failed ones last, the user's upstream proxy
// when one is set), which a browser view on its own does not: it takes the
// one address the system's DNS gives, which may be the one a network does
// not let through.
//
// It is not the VPN's proxy. It needs neither an account nor the VPN on,
// since the browser sign-in adds the first account. It serves only while
// armed (the app arms it when it opens the sign-in page, and disarms it
// when the page closes), and only HTTPS to the hosts a sign-in uses
// (Allowed): other programs on the device can reach loopback too, and must
// not use it to go around the VPN.
package signinproxy

import (
	"bufio"
	"context"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"strconv"
	"strings"
	"sync"
	"time"

	"dicodeping/fox/internal/logx"
)

// DialFunc opens the connection to a sign-in host.
type DialFunc func(ctx context.Context, network, address string) (net.Conn, error)

const (
	// ArmFor is how long one Arm lasts when the app does not disarm the
	// proxy (it was closed while the page was open).
	ArmFor = 30 * time.Minute
	// requestTimeout bounds reading a CONNECT request.
	requestTimeout = 15 * time.Second
	// dialTimeout bounds connecting to a sign-in host.
	dialTimeout = 30 * time.Second
)

// allowedDomains are the domains whose hosts a sign-in on
// accounts.firefox.com uses, the domain itself included.
var allowedDomains = []string{"firefox.com", "mozilla.com", "mozilla.org", "mozilla.net"}

// allowedHosts are the pages of the Google and Apple sign-ins that
// accounts.firefox.com offers ("Continue with Google", "Continue with
// Apple"); accounts made with them have no password.
var allowedHosts = map[string]bool{
	"accounts.google.com":       true,
	"accounts.youtube.com":      true,
	"apis.google.com":           true,
	"play.google.com":           true,
	"www.google.com":            true,
	"ssl.gstatic.com":           true,
	"www.gstatic.com":           true,
	"fonts.gstatic.com":         true,
	"fonts.googleapis.com":      true,
	"lh3.googleusercontent.com": true,
	"appleid.apple.com":         true,
	"appleid.cdn-apple.com":     true,
	"idmsa.apple.com":           true,
	"iforgot.apple.com":         true,
	"www.apple.com":             true,
}

// Allowed reports whether host is one the sign-in uses. Addresses are
// refused: the sign-in names its hosts.
func Allowed(host string) bool {
	host = strings.ToLower(strings.TrimSuffix(host, "."))
	if host == "" || net.ParseIP(host) != nil {
		return false
	}
	if allowedHosts[host] {
		return true
	}
	for _, d := range allowedDomains {
		if host == d || strings.HasSuffix(host, "."+d) {
			return true
		}
	}
	return false
}

// Server is a running sign-in proxy.
type Server struct {
	ln   net.Listener
	dial DialFunc
	// now replaces time.Now in tests.
	now func() time.Time

	mu         sync.Mutex
	armedUntil time.Time
	closed     bool
	// tunnels are the open connections of the browser view, closed when
	// the proxy is disarmed or closed.
	tunnels map[net.Conn]struct{}
	wg      sync.WaitGroup
}

// Listen starts a proxy on 127.0.0.1:preferredPort, or on a free port when
// that one cannot be had (or is 0). The app asks for the port it used
// before: a Windows browser view keeps the proxy it was started with for
// the app's whole run. The proxy starts disarmed.
func Listen(preferredPort int, dial DialFunc) (*Server, error) {
	var ln net.Listener
	if preferredPort > 0 && preferredPort <= 65535 {
		ln, _ = net.Listen("tcp", net.JoinHostPort("127.0.0.1", strconv.Itoa(preferredPort)))
	}
	if ln == nil {
		var err error
		if ln, err = net.Listen("tcp", "127.0.0.1:0"); err != nil {
			return nil, err
		}
	}
	s := &Server{ln: ln, dial: dial, now: time.Now, tunnels: make(map[net.Conn]struct{})}
	s.wg.Add(1)
	go s.serve()
	return s, nil
}

// Addr is the proxy's address, "127.0.0.1:port".
func (s *Server) Addr() string { return s.ln.Addr().String() }

// Arm lets the proxy serve for ArmFor from now.
func (s *Server) Arm() {
	s.mu.Lock()
	s.armedUntil = s.now().Add(ArmFor)
	s.mu.Unlock()
}

// Disarm stops serving and closes the browser view's open connections.
func (s *Server) Disarm() {
	s.mu.Lock()
	s.armedUntil = time.Time{}
	s.closeTunnelsLocked()
	s.mu.Unlock()
}

func (s *Server) armed() bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.now().Before(s.armedUntil)
}

// Close stops the proxy and waits for its connections to end.
func (s *Server) Close() error {
	s.mu.Lock()
	s.closed = true
	s.armedUntil = time.Time{}
	s.closeTunnelsLocked()
	s.mu.Unlock()
	err := s.ln.Close()
	s.wg.Wait()
	return err
}

func (s *Server) closeTunnelsLocked() {
	for c := range s.tunnels {
		c.Close()
	}
	clear(s.tunnels)
}

// track records c as open; it reports false once the proxy is closed.
func (s *Server) track(c net.Conn) bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.closed {
		return false
	}
	s.tunnels[c] = struct{}{}
	return true
}

func (s *Server) untrack(c net.Conn) {
	s.mu.Lock()
	delete(s.tunnels, c)
	s.mu.Unlock()
}

func (s *Server) serve() {
	defer s.wg.Done()
	for {
		c, err := s.ln.Accept()
		if err != nil {
			if errors.Is(err, net.ErrClosed) {
				return
			}
			// A passing failure (out of file handles): wait a moment.
			time.Sleep(50 * time.Millisecond)
			continue
		}
		if !s.track(c) {
			c.Close()
			continue
		}
		s.wg.Add(1)
		go func() {
			defer s.wg.Done()
			defer s.untrack(c)
			defer c.Close()
			s.handle(c)
		}()
	}
}

func (s *Server) handle(c net.Conn) {
	_ = c.SetReadDeadline(time.Now().Add(requestTimeout))
	br := bufio.NewReader(c)
	req, err := http.ReadRequest(br)
	if err != nil {
		return
	}
	if req.Method != http.MethodConnect {
		reply(c, http.StatusMethodNotAllowed)
		return
	}
	host, port, err := net.SplitHostPort(req.Host)
	if err != nil || port != "443" || !Allowed(host) {
		// Not a sign-in host: another program's destination, hidden as
		// the proxy hides its own.
		logx.Debug("sign-in proxy refused a destination the sign-in does not use target=%s", logx.Target(req.Host))
		reply(c, http.StatusForbidden)
		return
	}
	if !s.armed() {
		logx.Debug("sign-in proxy refused a connection while no sign-in is open target=%s", req.Host)
		reply(c, http.StatusForbidden)
		return
	}

	ctx, cancel := context.WithTimeout(context.Background(), dialTimeout)
	up, err := s.dial(ctx, "tcp", req.Host)
	cancel()
	if err != nil {
		logx.Warn("sign-in proxy could not connect target=%s err=%s", req.Host, logx.Err(err))
		reply(c, http.StatusBadGateway)
		return
	}
	defer up.Close()
	if !s.track(up) {
		return
	}
	defer s.untrack(up)

	_ = c.SetReadDeadline(time.Time{})
	if _, err := io.WriteString(c, "HTTP/1.1 200 Connection Established\r\n\r\n"); err != nil {
		return
	}
	logx.Debug("sign-in proxy connected target=%s", req.Host)
	// Either way ending ends the tunnel: the deferred closes stop the
	// other copy. br first gives up what the browser sent after its
	// request (the start of its TLS handshake).
	done := make(chan struct{}, 2)
	go func() { io.Copy(up, br); done <- struct{}{} }()
	go func() { io.Copy(c, up); done <- struct{}{} }()
	<-done
}

func reply(c net.Conn, status int) {
	fmt.Fprintf(c, "HTTP/1.1 %d %s\r\nContent-Length: 0\r\nConnection: close\r\n\r\n", status, http.StatusText(status))
}
