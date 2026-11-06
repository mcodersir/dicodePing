package proxy

import (
	"context"
	"crypto/tls"
	"crypto/x509"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"strings"
	"time"
)

const maxExitCheckResponseSize = 64 * 1024

// The exit check asks for the public IPv4 and IPv6 address separately and
// at the same time: each service host has addresses of one family only, so
// Mozilla's proxy has to reach it over that family, and the service sees
// the exit address of that family. A dual-stack host would show only the
// family the proxy prefers (IPv6). Cloudflare's trace, at its IP addresses,
// comes first: its country is the one the many sites behind Cloudflare see,
// from a database kept current. ip.sb (the service v2rayNG uses) is the
// fallback, and is also asked alongside for the city and network, which the
// trace does not report; its country never replaces Cloudflare's. Tests
// replace the lists.
var (
	exitCheckIPv4URLs = []string{"https://1.1.1.1/cdn-cgi/trace", "https://api-ipv4.ip.sb/geoip"}
	exitCheckIPv6URLs = []string{"https://[2606:4700:4700::1111]/cdn-cgi/trace", "https://api-ipv6.ip.sb/geoip"}
	exitDetailsURLs   = []string{"https://api-ipv4.ip.sb/geoip", "https://api-ipv6.ip.sb/geoip"}
)

// exitProbeRoots replaces the system roots in tests.
var exitProbeRoots *x509.CertPool

// ExitProbeResult is the public address the traffic leaves Mozilla's
// network from: what websites see. An exit without IPv6 has no IPv6
// address. City, Network (the ISP or organization), and ASN are empty when
// the services do not report them.
type ExitProbeResult struct {
	IPv4        string
	IPv6        string
	CountryCode string
	City        string
	Network     string
	ASN         int
	Latency     time.Duration
	ProbeHost   string
}

// IP returns the IPv4 address, or the IPv6 address without one.
func (r ExitProbeResult) IP() string {
	if r.IPv4 != "" {
		return r.IPv4
	}
	return r.IPv6
}

// Place describes the exit for people: the country code, then the city and
// network when known, such as "NL, Amsterdam, Example Hosting".
func (r ExitProbeResult) Place() string {
	parts := []string{r.CountryCode}
	for _, p := range []string{r.City, r.Network} {
		if p != "" {
			parts = append(parts, p)
		}
	}
	return strings.Join(parts, ", ")
}

func ExitProbeHost(rawURL string) string {
	probeURL, err := url.Parse(rawURL)
	if err != nil || probeURL.Hostname() == "" {
		return "<invalid>"
	}
	return probeURL.Hostname()
}

// VerifyExit finds the public IPv4 and IPv6 address of the exit through
// opener, both at once; timeout applies to each service asked. It fails
// only when neither family answers.
func VerifyExit(opener tunnelOpener, timeout time.Duration) (ExitProbeResult, error) {
	type answer struct {
		result ExitProbeResult
		err    error
	}
	v4, v6, more := make(chan answer, 1), make(chan answer, 1), make(chan answer, 1)
	go func() { r, err := askFamily(opener, exitCheckIPv4URLs, false, timeout); v4 <- answer{r, err} }()
	go func() { r, err := askFamily(opener, exitCheckIPv6URLs, true, timeout); v6 <- answer{r, err} }()
	go func() { r, err := askDetails(opener, exitDetailsURLs, timeout); more <- answer{r, err} }()
	a4, a6, details := <-v4, <-v6, <-more
	if a4.err != nil && a6.err != nil {
		return ExitProbeResult{}, fmt.Errorf("IPv4: %w; IPv6: %w", a4.err, a6.err)
	}
	// The country comes from the IPv4 answer, else the IPv6 one; the city
	// and network from whichever answer names them.
	place := a4.result
	if a4.err != nil {
		place = a6.result
	}
	for _, a := range []answer{a4, a6, details} {
		if place.City == "" && a.err == nil && a.result.City != "" {
			place.City, place.Network, place.ASN = a.result.City, a.result.Network, a.result.ASN
		}
	}
	place.IPv4, place.IPv6 = a4.result.IPv4, a6.result.IPv6
	place.Latency = max(a4.result.Latency, a6.result.Latency)
	return place, nil
}

// askDetails asks the services in urls, in order, for the exit's city and
// network; the first that names a city answers.
func askDetails(opener tunnelOpener, urls []string, timeout time.Duration) (ExitProbeResult, error) {
	var errs []error
	for _, u := range urls {
		result, err := verifyExitAt(opener, u, timeout)
		if err == nil && result.City == "" {
			err = errors.New("no city in the answer")
		}
		if err == nil {
			return result, nil
		}
		errs = append(errs, fmt.Errorf("%s: %w", ExitProbeHost(u), err))
	}
	return ExitProbeResult{}, errors.Join(errs...)
}

// askFamily asks the services in urls, in order, until one reports an
// address of the wanted family.
func askFamily(opener tunnelOpener, urls []string, wantIPv6 bool, timeout time.Duration) (ExitProbeResult, error) {
	var errs []error
	for _, u := range urls {
		result, err := verifyExitAt(opener, u, timeout)
		if err == nil {
			ip := net.ParseIP(result.IPv4)
			if isIPv6 := ip.To4() == nil; isIPv6 != wantIPv6 {
				err = fmt.Errorf("answered with %s, another address family", result.IPv4)
			} else if wantIPv6 {
				result.IPv4, result.IPv6 = "", result.IPv4
			}
		}
		if err == nil {
			return result, nil
		}
		errs = append(errs, fmt.Errorf("%s: %w", ExitProbeHost(u), err))
	}
	if len(errs) == 0 {
		return ExitProbeResult{}, errors.New("no exit check service")
	}
	return ExitProbeResult{}, errors.Join(errs...)
}

// verifyExitAt asks one service; the address it reports is in IPv4
// whatever its family, for askFamily to sort.
func verifyExitAt(opener tunnelOpener, rawURL string, timeout time.Duration) (ExitProbeResult, error) {
	if opener == nil {
		return ExitProbeResult{}, fmt.Errorf("nil tunnel opener")
	}
	probeURL, err := url.Parse(rawURL)
	if err != nil {
		return ExitProbeResult{}, fmt.Errorf("parsing exit check URL: %w", err)
	}
	if !strings.EqualFold(probeURL.Scheme, "https") || probeURL.Hostname() == "" {
		return ExitProbeResult{}, fmt.Errorf("exit check URL must use HTTPS and include a host")
	}

	transport := &http.Transport{
		Proxy:               nil,
		DisableKeepAlives:   true,
		TLSHandshakeTimeout: timeout,
		TLSClientConfig: &tls.Config{
			MinVersion: tls.VersionTLS12,
			RootCAs:    exitProbeRoots,
		},
		DialContext: func(ctx context.Context, _, authority string) (net.Conn, error) {
			return openTunnelContext(ctx, opener, authority)
		},
	}
	defer transport.CloseIdleConnections()
	client := &http.Client{Transport: transport, Timeout: timeout}

	request, err := http.NewRequest(http.MethodGet, probeURL.String(), nil)
	if err != nil {
		return ExitProbeResult{}, fmt.Errorf("creating exit verification request: %w", err)
	}
	request.Header.Set("Accept", "text/plain, application/json")
	request.Header.Set("User-Agent", "arman-vpn-exit-check/1")

	started := time.Now()
	response, err := client.Do(request)
	if err != nil {
		return ExitProbeResult{}, fmt.Errorf("requesting exit verification endpoint: %w", err)
	}
	defer response.Body.Close()
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		return ExitProbeResult{}, fmt.Errorf("exit verification endpoint returned HTTP %d", response.StatusCode)
	}
	body, err := io.ReadAll(io.LimitReader(response.Body, maxExitCheckResponseSize+1))
	if err != nil {
		return ExitProbeResult{}, fmt.Errorf("reading exit verification response: %w", err)
	}
	if len(body) > maxExitCheckResponseSize {
		return ExitProbeResult{}, fmt.Errorf("exit verification response exceeds %d bytes", maxExitCheckResponseSize)
	}
	result, err := parseExitProbeResponse(body)
	if err != nil {
		return ExitProbeResult{}, err
	}
	result.Latency = time.Since(started)
	result.ProbeHost = probeURL.Hostname()
	return result, nil
}

func openTunnelContext(ctx context.Context, opener tunnelOpener, authority string) (net.Conn, error) {
	type tunnelResult struct {
		conn net.Conn
		err  error
	}
	resultCh := make(chan tunnelResult)
	go func() {
		conn, err := opener.OpenTunnel(authority)
		select {
		case resultCh <- tunnelResult{conn: conn, err: err}:
		case <-ctx.Done():
			if conn != nil {
				_ = conn.Close()
			}
		}
	}()

	select {
	case result := <-resultCh:
		return result.conn, result.err
	case <-ctx.Done():
		return nil, ctx.Err()
	}
}

// parseExitProbeResponse reads a key=value trace (Cloudflare) or a JSON
// object (ip.sb and similar services).
func parseExitProbeResponse(body []byte) (ExitProbeResult, error) {
	var result ExitProbeResult
	fields := make(map[string]string)
	for _, line := range strings.Split(string(body), "\n") {
		key, value, ok := strings.Cut(strings.TrimSpace(line), "=")
		if ok {
			fields[strings.ToLower(strings.TrimSpace(key))] = strings.TrimSpace(value)
		}
	}

	ip := firstNonEmpty(fields["ip"], fields["query"])
	countryCode := firstNonEmpty(fields["loc"], fields["country_code"], fields["countrycode"])
	if ip == "" || countryCode == "" {
		var payload map[string]any
		if err := json.Unmarshal(body, &payload); err == nil {
			ip = firstNonEmpty(ip, jsonString(payload, "ip"), jsonString(payload, "query"))
			countryCode = firstNonEmpty(countryCode, jsonString(payload, "country_code"), jsonString(payload, "countryCode"))
			result.City = strings.TrimSpace(jsonString(payload, "city"))
			result.Network = strings.TrimSpace(firstNonEmpty(jsonString(payload, "isp"), jsonString(payload, "organization"), jsonString(payload, "asn_organization")))
			if asn, ok := payload["asn"].(float64); ok && asn > 0 {
				result.ASN = int(asn)
			}
		}
	}

	ip = strings.TrimSpace(ip)
	if net.ParseIP(ip) == nil {
		return ExitProbeResult{}, fmt.Errorf("exit verification response did not contain a valid IP address")
	}
	countryCode = strings.ToUpper(strings.TrimSpace(countryCode))
	if len(countryCode) != 2 || countryCode[0] < 'A' || countryCode[0] > 'Z' || countryCode[1] < 'A' || countryCode[1] > 'Z' {
		return ExitProbeResult{}, fmt.Errorf("exit verification response did not contain a valid two-letter country code")
	}
	result.IPv4, result.CountryCode = ip, countryCode
	return result, nil
}

func jsonString(payload map[string]any, key string) string {
	value, _ := payload[key].(string)
	return value
}

func firstNonEmpty(values ...string) string {
	for _, value := range values {
		if strings.TrimSpace(value) != "" {
			return value
		}
	}
	return ""
}
