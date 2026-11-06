package proxy

import (
	"context"
	"crypto/x509"
	"errors"
	"fmt"
	"net"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

func TestParseExitProbeResponse(t *testing.T) {
	t.Parallel()

	tests := []struct {
		name        string
		body        string
		wantIP      string
		wantCountry string
	}{
		{
			name:        "cloudflare trace",
			body:        "fl=123\nip=203.0.113.8\nloc=jp\ntls=TLSv1.3\n",
			wantIP:      "203.0.113.8",
			wantCountry: "JP",
		},
		{
			name:        "json fields",
			body:        `{"ip":"2001:db8::8","country_code":"DE"}`,
			wantIP:      "2001:db8::8",
			wantCountry: "DE",
		},
		{
			name:        "alternate json fields",
			body:        `{"query":"198.51.100.9","countryCode":"US"}`,
			wantIP:      "198.51.100.9",
			wantCountry: "US",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got, err := parseExitProbeResponse([]byte(tt.body))
			if err != nil {
				t.Fatalf("parseExitProbeResponse returned error: %v", err)
			}
			if got.IPv4 != tt.wantIP || got.CountryCode != tt.wantCountry {
				t.Fatalf("expected %s/%s, got %s/%s", tt.wantIP, tt.wantCountry, got.IPv4, got.CountryCode)
			}
		})
	}
}

func TestParseExitProbeResponseRejectsMissingFields(t *testing.T) {
	t.Parallel()

	if _, err := parseExitProbeResponse([]byte("ip=not-an-ip\nloc=USA\n")); err == nil {
		t.Fatal("expected invalid probe response to be rejected")
	}
}

func TestOpenTunnelContextClosesConnectionThatArrivesAfterCancellation(t *testing.T) {
	t.Parallel()

	client, peer := net.Pipe()
	defer peer.Close()
	tracked := &closeTrackingConn{Conn: client}
	opener := &delayedTunnelOpener{
		started: make(chan struct{}),
		release: make(chan struct{}),
		conn:    tracked,
	}
	ctx, cancel := context.WithCancel(context.Background())
	type result struct {
		conn net.Conn
		err  error
	}
	resultCh := make(chan result, 1)
	go func() {
		conn, err := openTunnelContext(ctx, opener, "example.com:443")
		resultCh <- result{conn: conn, err: err}
	}()

	<-opener.started
	cancel()
	got := <-resultCh
	if got.conn != nil || !errors.Is(got.err, context.Canceled) {
		t.Fatalf("expected canceled dial, got conn=%v err=%v", got.conn, got.err)
	}
	close(opener.release)
	waitForCondition(t, time.Second, tracked.closed.Load)
}

// The shape of an api.ip.sb/geoip answer (documentation addresses).
func TestParseIPSBGeoIP(t *testing.T) {
	body := `{"region":"North Holland","organization":"Example Hosting","region_code":"NH","isp":"Example ISP","city":"Amsterdam","asn_organization":"Example AS","asn":64500,"latitude":52.3,"ip":"2001:db8::1","continent_code":"EU","offset":3600,"country":"Netherlands","timezone":"Europe\/Amsterdam","country_code":"NL","longitude":4.9}`
	got, err := parseExitProbeResponse([]byte(body))
	if err != nil {
		t.Fatal(err)
	}
	if got.IPv4 != "2001:db8::1" || got.CountryCode != "NL" || got.City != "Amsterdam" || got.Network != "Example ISP" || got.ASN != 64500 {
		t.Fatalf("got %+v", got)
	}
	if got.Place() != "NL, Amsterdam, Example ISP" {
		t.Fatalf("place %q", got.Place())
	}
}

// tunnelToAddr opens every tunnel to one local server.
type tunnelToAddr string

func (a tunnelToAddr) OpenTunnel(string) (net.Conn, error) { return net.Dial("tcp", string(a)) }

// The IPv4 and IPv6 addresses are asked separately; a failing service is
// replaced by the next one of its family, and an answer of the wrong family
// does not count.
func TestVerifyExitFindsBothFamilies(t *testing.T) {
	server := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/v4-busy":
			http.Error(w, "busy", http.StatusServiceUnavailable)
		case "/v4-trace":
			fmt.Fprint(w, "ip=203.0.113.8\nloc=BE\n")
		case "/v6-geoip":
			fmt.Fprint(w, `{"ip":"2001:db8::8","country_code":"BE","city":"Brussels","isp":"Example VPN"}`)
		case "/v6-wrong-family":
			fmt.Fprint(w, `{"ip":"203.0.113.9","country_code":"BE"}`)
		}
	}))
	defer server.Close()
	pool := x509.NewCertPool()
	pool.AddCert(server.Certificate())
	exitProbeRoots = pool
	oldV4, oldV6, oldDetails := exitCheckIPv4URLs, exitCheckIPv6URLs, exitDetailsURLs
	t.Cleanup(func() {
		exitProbeRoots, exitCheckIPv4URLs, exitCheckIPv6URLs, exitDetailsURLs = nil, oldV4, oldV6, oldDetails
	})
	opener := tunnelToAddr(server.Listener.Addr().String())

	exitDetailsURLs = []string{"https://example.com/v4-busy"}
	exitCheckIPv4URLs = []string{"https://example.com/v4-busy", "https://example.com/v4-trace"}
	exitCheckIPv6URLs = []string{"https://example.com/v6-wrong-family", "https://example.com/v6-geoip"}
	got, err := VerifyExit(opener, 5*time.Second)
	if err != nil || got.IPv4 != "203.0.113.8" || got.IPv6 != "2001:db8::8" {
		t.Fatalf("got %+v %v", got, err)
	}
	// The place comes from the answer that names the city.
	if got.Place() != "BE, Brussels, Example VPN" || got.IP() != "203.0.113.8" {
		t.Fatalf("place %q ip %q", got.Place(), got.IP())
	}

	// An exit without IPv6 still reports its IPv4 address.
	exitCheckIPv6URLs = []string{"https://example.com/v6-wrong-family"}
	got, err = VerifyExit(opener, 5*time.Second)
	if err != nil || got.IPv4 != "203.0.113.8" || got.IPv6 != "" || got.CountryCode != "BE" {
		t.Fatalf("without IPv6: %+v %v", got, err)
	}

	// Nothing answers: the error names both families.
	exitCheckIPv4URLs = []string{"https://example.com/v4-busy"}
	if _, err := VerifyExit(opener, 5*time.Second); err == nil || !strings.Contains(err.Error(), "IPv4") || !strings.Contains(err.Error(), "HTTP 503") {
		t.Fatalf("expected both families to fail: %v", err)
	}
}

// Cloudflare's country wins; ip.sb, asked alongside, adds only the city and
// network, even when its database names another country.
func TestVerifyExitTakesTheCountryFromCloudflare(t *testing.T) {
	server := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/trace4":
			fmt.Fprint(w, "ip=203.0.113.8\nloc=GB\n")
		case "/trace6":
			fmt.Fprint(w, "ip=2001:db8::8\nloc=GB\n")
		case "/geoip":
			fmt.Fprint(w, `{"ip":"203.0.113.8","country_code":"US","city":"London","isp":"Example VPN"}`)
		}
	}))
	defer server.Close()
	pool := x509.NewCertPool()
	pool.AddCert(server.Certificate())
	exitProbeRoots = pool
	oldV4, oldV6, oldDetails := exitCheckIPv4URLs, exitCheckIPv6URLs, exitDetailsURLs
	t.Cleanup(func() {
		exitProbeRoots, exitCheckIPv4URLs, exitCheckIPv6URLs, exitDetailsURLs = nil, oldV4, oldV6, oldDetails
	})
	exitCheckIPv4URLs = []string{"https://example.com/trace4"}
	exitCheckIPv6URLs = []string{"https://example.com/trace6"}
	exitDetailsURLs = []string{"https://example.com/geoip"}

	got, err := VerifyExit(tunnelToAddr(server.Listener.Addr().String()), 5*time.Second)
	if err != nil || got.CountryCode != "GB" || got.Place() != "GB, London, Example VPN" {
		t.Fatalf("got %+v %v", got, err)
	}
}
