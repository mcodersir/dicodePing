package main

import (
	"context"
	"crypto/tls"
	"encoding/binary"
	"errors"
	"io"
	"net"
	"net/http"
	"strconv"
	"strings"
	"sync"
	"time"
)

func (p *provider) prepareRelay(ctx context.Context, country, listen string) (string, error) {
	// A proxy pass is the authorization gate. Optional account metadata must
	// not prevent a working relay from starting on a filtered mobile network.
	if err := p.refreshProxyPass(ctx, false); err != nil {
		return "", err
	}
	country = strings.ToUpper(strings.TrimSpace(country))
	if country == "" {
		country = "REC"
	}
	candidates, err := initialRelayLocations(country, func() ([]Location, error) { return p.locations(ctx) })
	if err != nil {
		return "", err
	}
	if country != "REC" {
		selected := make([]Location, 0, len(candidates))
		for _, candidate := range candidates {
			if strings.EqualFold(country, candidate.CountryCode) {
				selected = append(selected, candidate)
			}
		}
		candidates = selected
	}
	p.streams = p.relayTransport()
	p.relayPool = []*http.Transport{p.streams, p.relayTransport(), p.relayTransport(), p.relayTransport()}
	reached := false
	for index := 0; index < len(candidates) && index < 4; index++ {
		candidate := candidates[index]
		if country != "REC" && !strings.EqualFold(country, candidate.CountryCode) {
			continue
		}
		if ctx.Err() != nil {
			return "", ctx.Err()
		}
		p.selected = candidate
		var e error
		reached, e = p.probeRelay(ctx)
		if reached {
			break
		}
		var api *ProviderError
		if errors.As(e, &api) && (api.Code == "quota_exceeded" || api.Code == "login_required") {
			return "", api
		}
		if country == "REC" && index == 0 {
			// Catalog fallback is needed only when the recommended anycast route fails.
			if alternatives, lookupErr := p.locations(ctx); lookupErr == nil {
				candidates = append(candidates, alternatives...)
			}
		}
	}
	if !reached {
		p.closeRelays()
		return "", &ProviderError{Code: "unreachable", Message: "No selected Firefox VPN location passed the real traffic test; no direct fallback was used."}
	}
	if listen == "" {
		listen = "127.0.0.1:0"
	}
	host, _, err := net.SplitHostPort(listen)
	if err != nil || host != "127.0.0.1" {
		return "", &ProviderError{Code: "input", Message: "Fox helper must listen on IPv4 loopback"}
	}
	p.listener, err = net.Listen("tcp", listen)
	if err != nil {
		return "", &ProviderError{Code: "port_in_use", Message: "The Fox local SOCKS port is occupied. Stop the other proxy or use its SOCKS profile."}
	}
	return p.listener.Addr().String(), nil
}

// Validate a real HTTPS response through CONNECT. A single blocked probe host
// does not reject a usable exit. There is no direct-network fallback.
func (p *provider) probeRelay(ctx context.Context) (bool, error) {
	targets := []struct {
		url, body string
		status    int
	}{
		{"https://detectportal.firefox.com/success.txt", "success", 200},
		{"https://cp.cloudflare.com/generate_204", "", 204},
	}
	var last error
	for _, target := range targets {
		probeCtx, cancel := context.WithTimeout(ctx, 4*time.Second)
		client := p.dohClient()
		req, _ := http.NewRequestWithContext(probeCtx, "GET", target.url, nil)
		resp, err := client.Do(req)
		ok := false
		if err == nil {
			body, readErr := io.ReadAll(io.LimitReader(resp.Body, 8193))
			resp.Body.Close()
			err = readErr
			ok = err == nil && resp.StatusCode == target.status && strings.TrimSpace(string(body)) == target.body
		}
		client.CloseIdleConnections()
		cancel()
		if ok {
			return true, nil
		}
		last = err
		var api *ProviderError
		if errors.As(err, &api) && (api.Code == "quota_exceeded" || api.Code == "login_required") {
			return false, api
		}
		if ctx.Err() != nil {
			return false, ctx.Err()
		}
	}
	return false, last
}

func (p *provider) openTunnel(ctx context.Context, authority string) (net.Conn, error) {
	conn, err := p.openTunnelAttempt(ctx, authority, true)
	var api *ProviderError
	// Retry establishment on a different carrier only before any application
	// payload has been sent. Established byte streams are never replayed.
	if err != nil && ctx.Err() == nil && !errors.As(err, &api) {
		return p.openTunnelAttempt(ctx, authority, true)
	}
	return conn, err
}
func (p *provider) openTunnelAttempt(ctx context.Context, authority string, refresh bool) (net.Conn, error) {
	pass, err := p.proxyPass(ctx)
	if err != nil {
		return nil, err
	}
	child, cancel := context.WithCancel(ctx)
	reader, writer := io.Pipe()
	request, err := http.NewRequestWithContext(child, "CONNECT", "https://"+net.JoinHostPort(p.selected.Host, strconv.Itoa(p.selected.Port)), reader)
	if err != nil {
		cancel()
		reader.Close()
		writer.Close()
		return nil, err
	}
	request.Host = authority
	request.ContentLength = -1
	request.Header.Set("Proxy-Authorization", "Bearer "+pass)
	request.Header.Set("User-Agent", userAgent)
	resp, err := p.nextRelay().RoundTrip(request)
	if err != nil {
		cancel()
		reader.Close()
		writer.Close()
		return nil, err
	}
	if resp.ProtoMajor != 2 || resp.StatusCode != 200 {
		cancel()
		resp.Body.Close()
		reader.Close()
		writer.Close()
		if refresh && (resp.StatusCode == 401 || resp.StatusCode == 407) {
			p.mutex.Lock()
			if p.pass == pass {
				p.pass = ""
				p.passExpiry = 0
			}
			p.mutex.Unlock()
			return p.openTunnelAttempt(ctx, authority, false)
		}
		code, msg := "unreachable", "Firefox proxy rejected CONNECT"
		if resp.StatusCode == 429 {
			return nil, proxyLimitError(resp.Header)
		}
		if resp.StatusCode == 401 || resp.StatusCode == 407 {
			code = "login_required"
			msg = "The proxy pass was rejected; sign in again"
		}
		return nil, &ProviderError{Code: code, Status: resp.StatusCode, Message: msg}
	}
	return &tunnelConn{input: resp.Body, output: writer, cancel: cancel}, nil
}

type tunnelConn struct {
	input  io.ReadCloser
	output *io.PipeWriter
	cancel context.CancelFunc
	once   sync.Once
	timer  *time.Timer
	mu     sync.Mutex
}

func (c *tunnelConn) Read(b []byte) (int, error)  { return c.input.Read(b) }
func (c *tunnelConn) Write(b []byte) (int, error) { return c.output.Write(b) }
func (c *tunnelConn) Close() error {
	c.once.Do(func() {
		c.cancel()
		c.input.Close()
		c.output.Close()
		c.mu.Lock()
		if c.timer != nil {
			c.timer.Stop()
		}
		c.mu.Unlock()
	})
	return nil
}
func (c *tunnelConn) CloseWrite() error    { return c.output.Close() }
func (c *tunnelConn) LocalAddr() net.Addr  { return &net.TCPAddr{IP: net.IPv4(127, 0, 0, 1)} }
func (c *tunnelConn) RemoteAddr() net.Addr { return &net.TCPAddr{IP: net.IPv4(127, 0, 0, 1)} }
func (c *tunnelConn) SetDeadline(t time.Time) error {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.timer != nil {
		c.timer.Stop()
	}
	if !t.IsZero() {
		c.timer = time.AfterFunc(time.Until(t), func() { c.cancel() })
	}
	return nil
}
func (c *tunnelConn) SetReadDeadline(t time.Time) error  { return c.SetDeadline(t) }
func (c *tunnelConn) SetWriteDeadline(t time.Time) error { return c.SetDeadline(t) }
func (p *provider) openDialTunnel(ctx context.Context, address string) (net.Conn, error) {
	life, cancel := context.WithCancel(context.WithoutCancel(ctx))
	stop := context.AfterFunc(ctx, cancel)
	conn, err := p.openTunnel(life, address)
	if !stop() || err != nil {
		cancel()
		if conn != nil {
			conn.Close()
		}
		if err == nil {
			err = ctx.Err()
		}
		return nil, err
	}
	original := conn.(*tunnelConn).cancel
	conn.(*tunnelConn).cancel = func() { original(); cancel() }
	return conn, nil
}
func (p *provider) dohClient() *http.Client {
	return &http.Client{Timeout: 12 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }, Transport: &http.Transport{Proxy: nil, ForceAttemptHTTP2: true, DialContext: func(ctx context.Context, network, address string) (net.Conn, error) {
		// net/http cancels its DialContext after acquiring a connection. That
		// cancellation must not destroy the established HTTP/2 CONNECT stream.
		return p.openDialTunnel(ctx, address)
	}, TLSClientConfig: &tls.Config{RootCAs: p.roots, MinVersion: tls.VersionTLS12}}}
}
func (p *provider) serve(ctx context.Context) error {
	if p.listener == nil {
		return errors.New("listener not prepared")
	}
	defer p.listener.Close()
	defer p.closeRelays()
	ctx, cancel := context.WithCancel(ctx)
	defer cancel()
	fatal := make(chan error, 1)
	slots := make(chan struct{}, 512)
	var wg sync.WaitGroup
	go func() { <-ctx.Done(); p.listener.Close() }()
	for {
		conn, err := p.listener.Accept()
		if err != nil {
			break
		}
		select {
		case slots <- struct{}{}:
		default:
			// Never stop Accept behind long-lived streams: fail excess local
			// connections promptly instead of a silent, unbounded listen queue.
			conn.Close()
			continue
		}
		wg.Add(1)
		go func() {
			defer wg.Done()
			defer func() { <-slots }()
			defer conn.Close()
			finished := make(chan struct{})
			defer close(finished)
			go func() {
				select {
				case <-ctx.Done():
					conn.Close()
				case <-finished:
				}
			}()
			err := p.socks(ctx, conn)
			var api *ProviderError
			if errors.As(err, &api) && (api.Code == "quota_exceeded" || api.Code == "login_required") {
				select {
				case fatal <- api:
				default:
				}
				cancel()
			}
		}()
	}
	cancel()
	wg.Wait()
	select {
	case err := <-fatal:
		return err
	default:
		return nil
	}
}
func socksAddress(r io.Reader) (string, error) {
	b := []byte{0}
	if _, e := io.ReadFull(r, b); e != nil {
		return "", e
	}
	var host string
	switch b[0] {
	case 1:
		buf := make([]byte, 4)
		if _, e := io.ReadFull(r, buf); e != nil {
			return "", e
		}
		host = net.IP(buf).String()
	case 4:
		buf := make([]byte, 16)
		if _, e := io.ReadFull(r, buf); e != nil {
			return "", e
		}
		host = net.IP(buf).String()
	case 3:
		if _, e := io.ReadFull(r, b); e != nil || b[0] == 0 {
			return "", errors.New("invalid hostname")
		}
		buf := make([]byte, int(b[0]))
		if _, e := io.ReadFull(r, buf); e != nil {
			return "", e
		}
		host = string(buf)
	default:
		return "", errors.New("invalid SOCKS address")
	}
	port := make([]byte, 2)
	if _, e := io.ReadFull(r, port); e != nil {
		return "", e
	}
	return net.JoinHostPort(host, strconv.Itoa(int(binary.BigEndian.Uint16(port)))), nil
}
func replySocks(c net.Conn, code byte, port int) error {
	_, err := c.Write([]byte{5, code, 0, 1, 127, 0, 0, 1, byte(port >> 8), byte(port)})
	return err
}
func (p *provider) socks(ctx context.Context, c net.Conn) error {
	c.SetDeadline(time.Now().Add(30 * time.Second))
	greeting := make([]byte, 2)
	if _, err := io.ReadFull(c, greeting); err != nil {
		return err
	}
	if greeting[0] != 5 || greeting[1] == 0 {
		return errors.New("invalid SOCKS greeting")
	}
	methods := make([]byte, int(greeting[1]))
	if _, e := io.ReadFull(c, methods); e != nil {
		return e
	}
	noAuth := false
	for _, m := range methods {
		noAuth = noAuth || m == 0
	}
	if !noAuth {
		c.Write([]byte{5, 255})
		return errors.New("unsupported SOCKS authentication")
	}
	c.Write([]byte{5, 0})
	header := make([]byte, 3)
	if _, e := io.ReadFull(c, header); e != nil {
		return e
	}
	if header[0] != 5 || header[2] != 0 {
		return errors.New("invalid SOCKS request")
	}
	authority, err := socksAddress(c)
	if err != nil {
		return err
	}
	if header[1] == 3 {
		return p.udpDNS(ctx, c)
	}
	if header[1] != 1 {
		replySocks(c, 7, 0)
		return errors.New("unsupported SOCKS command")
	}
	streamCtx, cancel := context.WithCancel(ctx)
	defer cancel()
	// Bound only CONNECT establishment, not the lifetime of the stream.
	// A socket deadline on the local client cannot cancel a hung upstream.
	connectCtx, finishConnect := context.WithTimeout(streamCtx, 25*time.Second)
	upstream, err := p.openDialTunnel(connectCtx, authority)
	finishConnect()
	if err != nil {
		replySocks(c, 5, 0)
		return err
	}
	defer upstream.Close()
	stopLifetime := context.AfterFunc(streamCtx, func() { upstream.Close() })
	defer stopLifetime()
	if err = replySocks(c, 0, 0); err != nil {
		return err
	}
	c.SetDeadline(time.Time{})
	done := make(chan struct{})
	go func() {
		io.Copy(upstream, c)
		if half, ok := upstream.(interface{ CloseWrite() error }); ok {
			half.CloseWrite()
		}
		close(done)
	}()
	_, err = io.Copy(c, upstream)
	c.Close()
	upstream.Close()
	<-done
	return err
}
func (p *provider) udpDNS(ctx context.Context, control net.Conn) error {
	udp, err := net.ListenUDP("udp", &net.UDPAddr{IP: net.IPv4(127, 0, 0, 1)})
	if err != nil {
		return err
	}
	defer udp.Close()
	replySocks(control, 0, udp.LocalAddr().(*net.UDPAddr).Port)
	control.SetDeadline(time.Time{})
	done := make(chan struct{})
	go func() { io.Copy(io.Discard, control); udp.Close(); close(done) }()
	client := p.dohClient()
	defer client.CloseIdleConnections()
	buffer := make([]byte, 8192)
	go func() {
		select {
		case <-ctx.Done():
			control.Close()
			udp.Close()
		case <-done:
		}
	}()
	for {
		n, peer, err := udp.ReadFromUDP(buffer)
		if err != nil {
			return nil
		}
		if !peer.IP.IsLoopback() || n < 10 || buffer[0] != 0 || buffer[1] != 0 || buffer[2] != 0 {
			continue
		}
		reader := strings.NewReader(string(buffer[3:n]))
		address, e := socksAddress(reader)
		if e != nil {
			continue
		}
		_, port, e := net.SplitHostPort(address)
		if e != nil || port != "53" {
			continue
		}
		offset := n - reader.Len()
		if n-offset < 12 {
			continue
		}
		query := append([]byte(nil), buffer[offset:n]...)
		packet := append([]byte(nil), buffer[:offset]...)
		request, e := http.NewRequestWithContext(ctx, "POST", "https://cloudflare-dns.com/dns-query", strings.NewReader(string(query)))
		if e != nil {
			continue
		}
		request.Header.Set("Content-Type", "application/dns-message")
		request.Header.Set("Accept", "application/dns-message")
		response, e := client.Do(request)
		if e != nil {
			continue
		}
		answer, e := io.ReadAll(io.LimitReader(response.Body, 4096))
		response.Body.Close()
		if e == nil && response.StatusCode == 200 {
			udp.WriteToUDP(append(packet, answer...), peer)
		}
	}
}

// The provider's recommended anycast endpoint is fixed; country choices use the catalog.
func initialRelayLocations(country string, catalog func() ([]Location, error)) ([]Location, error) {
	if country == "REC" {
		return []Location{{CountryCode: "REC", Host: "p.m1.fastly-masque.net", Port: 2499}}, nil
	}
	return catalog()
}
