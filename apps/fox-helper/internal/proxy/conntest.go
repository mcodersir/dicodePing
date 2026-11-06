package proxy

import (
	"context"
	"crypto/tls"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/http/httptrace"
	"sync"
	"time"
)

const (
	// ConnectionTestURL answers 204 with no body; requesting it through the
	// tunnel measures the full data path without downloading anything.
	ConnectionTestURL     = "https://www.google.com/generate_204"
	ConnectionTestTimeout = 15 * time.Second
)

// ConnectionTestResult is the outcome of a test request sent through the
// tunnel. ICMP ping cannot cross the CONNECT proxy, so the test measures
// the stages of an HTTPS request instead.
type ConnectionTestResult struct {
	At    time.Time `json:"at"`
	OK    bool      `json:"ok"`
	Error string    `json:"error,omitempty"`
	// ErrorCode is the Failure code of Error.
	ErrorCode  string `json:"error_code,omitempty"`
	Target     string `json:"target"`
	HTTPStatus int    `json:"http_status,omitempty"`
	// The stages follow each other: opening the tunnel, the TLS handshake,
	// then waiting for the response (ResponseMS). FirstByteMS counts from
	// the start, so it includes the stages before it.
	TunnelMS    int64  `json:"tunnel_ms"`
	TLSMS       int64  `json:"tls_ms"`
	ResponseMS  int64  `json:"response_ms"`
	FirstByteMS int64  `json:"first_byte_ms"`
	TotalMS     int64  `json:"total_ms"`
	ExitIPv4    string `json:"exit_ipv4,omitempty"`
	ExitIPv6    string `json:"exit_ipv6,omitempty"`
	ExitCountry string `json:"exit_country,omitempty"`
	ExitCity    string `json:"exit_city,omitempty"`
	ExitNetwork string `json:"exit_network,omitempty"`
	ExitError   string `json:"exit_error,omitempty"`
}

// Exit returns the public IP part of the result.
func (r ConnectionTestResult) Exit() ExitProbeResult {
	return ExitProbeResult{IPv4: r.ExitIPv4, IPv6: r.ExitIPv6, CountryCode: r.ExitCountry, City: r.ExitCity, Network: r.ExitNetwork}
}

// RunConnectionTest requests ConnectionTestURL through opener and then
// finds the public IP and its place, waiting exitTimeout for each service
// (0 skips that check).
func RunConnectionTest(opener tunnelOpener, target string, exitTimeout, timeout time.Duration) ConnectionTestResult {
	result := ConnectionTestResult{At: time.Now(), Target: target}
	var tunnelOpened, tlsStart, tlsDone, firstByte time.Time
	// tunnelUp is set once Mozilla opened the tunnel to the test site; a
	// dial still running after a timeout may set it late.
	var tunnelMu sync.Mutex
	tunnelUp := false

	transport := &http.Transport{
		Proxy:               nil,
		DisableKeepAlives:   true,
		TLSHandshakeTimeout: timeout,
		TLSClientConfig:     &tls.Config{MinVersion: tls.VersionTLS12},
		DialContext: func(ctx context.Context, _, authority string) (net.Conn, error) {
			conn, err := openTunnelContext(ctx, opener, authority)
			tunnelOpened = time.Now()
			if err == nil {
				tunnelMu.Lock()
				tunnelUp = true
				tunnelMu.Unlock()
			}
			return conn, err
		},
	}
	defer transport.CloseIdleConnections()
	client := &http.Client{Transport: transport, Timeout: timeout}

	trace := &httptrace.ClientTrace{
		TLSHandshakeStart:    func() { tlsStart = time.Now() },
		TLSHandshakeDone:     func(tls.ConnectionState, error) { tlsDone = time.Now() },
		GotFirstResponseByte: func() { firstByte = time.Now() },
	}
	ctx := httptrace.WithClientTrace(context.Background(), trace)
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, target, nil)
	if err != nil {
		result.Error, result.ErrorCode = err.Error(), FailureOther
		return result
	}
	req.Header.Set("User-Agent", "arman-vpn-connection-test/1")

	started := time.Now()
	resp, err := client.Do(req)
	if err == nil {
		_, _ = io.Copy(io.Discard, io.LimitReader(resp.Body, 64*1024))
		_ = resp.Body.Close()
		result.HTTPStatus = resp.StatusCode
	}
	result.TotalMS = time.Since(started).Milliseconds()
	result.TunnelMS = elapsedMS(started, tunnelOpened)
	result.TLSMS = elapsedMS(tlsStart, tlsDone)
	result.FirstByteMS = elapsedMS(started, firstByte)
	sent := tlsDone
	if sent.IsZero() {
		sent = tunnelOpened
	}
	result.ResponseMS = elapsedMS(sent, firstByte)
	tunnelMu.Lock()
	up := tunnelUp
	tunnelMu.Unlock()
	switch {
	case err != nil && up:
		// Mozilla connected; the test site, or the way to it from
		// Mozilla's exit, failed.
		result.Error, result.ErrorCode = err.Error(), FailureTestSite
	case err != nil:
		result.Error, result.ErrorCode = err.Error(), FailureCode(err)
	case resp.StatusCode >= 400:
		result.Error = fmt.Sprintf("the test site answered HTTP %d", resp.StatusCode)
		result.ErrorCode = FailureTestSite
	default:
		result.OK = true
	}

	if exitTimeout > 0 {
		exit, err := VerifyExit(opener, exitTimeout)
		if err != nil {
			result.ExitError = err.Error()
		} else {
			result.ExitIPv4, result.ExitIPv6 = exit.IPv4, exit.IPv6
			result.ExitCountry, result.ExitCity, result.ExitNetwork = exit.CountryCode, exit.City, exit.Network
		}
	}
	return result
}

// HTTPClient sends the program's own requests, such as list downloads,
// through the proxy's tunnels.
func (c *Controller) HTTPClient(timeout time.Duration) *http.Client {
	transport := &http.Transport{
		Proxy:               nil,
		TLSHandshakeTimeout: timeout,
		TLSClientConfig:     &tls.Config{MinVersion: tls.VersionTLS12},
		DialContext: func(ctx context.Context, _, authority string) (net.Conn, error) {
			return openTunnelContext(ctx, c, authority)
		},
	}
	return &http.Client{Transport: transport, Timeout: timeout}
}

func elapsedMS(from, to time.Time) int64 {
	if from.IsZero() || to.IsZero() || to.Before(from) {
		return 0
	}
	return to.Sub(from).Milliseconds()
}
