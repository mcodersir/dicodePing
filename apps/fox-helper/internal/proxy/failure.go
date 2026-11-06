package proxy

import (
	"context"
	"crypto/tls"
	"crypto/x509"
	"errors"
	"io"
	"net"
	"slices"
	"strings"
	"syscall"

	"dicodeping/fox/internal/accounts"
	"dicodeping/fox/internal/fxa"
	"dicodeping/fox/internal/guardian"
)

// Failure codes say why a connection through Mozilla failed, so the apps
// can tell the user in their language what is wrong instead of always
// blaming the internet; the error text stays for the details. The status
// view's wake_error_code and the connection test's error_code carry them.
const (
	// FailureNoNetwork: this device has no working network (no route, or
	// names do not resolve).
	FailureNoNetwork = "no_network"
	// FailureUnreachable: Mozilla's servers did not answer or the
	// connection was cut (timeouts, resets, failed TLS handshakes), as on
	// a network that blocks them.
	FailureUnreachable = "unreachable"
	// FailureInsideVPN: as unreachable, on a device whose own internet
	// already leaves through a VPN's exit (Fastly's network: another
	// Arman VPN, on this device or one whose proxy it uses), which lets
	// only web ports through, not Mozilla's proxy port.
	FailureInsideVPN = "inside_vpn"
	// FailureUpstreamProxy: as unreachable, through the user's own SOCKS5
	// proxy (network.upstream_proxy): the proxy, or its way to Mozilla.
	FailureUpstreamProxy = "upstream_proxy"
	// FailureRefused: a Mozilla proxy server refused the tunnel.
	FailureRefused = "refused"
	// FailureLocationRefused: the server of a location the user chose
	// kept refusing the tunnel (CONNECT 403 or 407) with a proxy pass
	// fetched after the first refusal: Mozilla does not let this account
	// use this location (LocationRefusedError).
	FailureLocationRefused = "location_refused"
	// FailureSignIn: the account must sign in again.
	FailureSignIn = "sign_in"
	// FailureQuota: the account's monthly data is used up.
	FailureQuota = "quota"
	// FailureNotEntitled: Mozilla does not let the account use the VPN.
	FailureNotEntitled = "not_entitled"
	// FailureRegion: Mozilla refuses requests from this region (HTTP 451).
	FailureRegion = "region"
	// FailureServer: Mozilla's service answered with a server error.
	FailureServer = "server"
	// FailureNoAccount: no account can be used now.
	FailureNoAccount = "no_account"
	// FailureTestSite: the tunnel opened, but the test site failed.
	FailureTestSite = "test_site"
	// FailureOther: anything else; the error text says what.
	FailureOther = "other"
)

// FailureCode classifies err, a failure to reach a site through Mozilla,
// into one of the Failure codes; "" for nil.
func FailureCode(err error) string {
	if err == nil {
		return ""
	}
	var noAccount *accounts.NoUsableAccountError
	var locationErr *LocationRefusedError
	var connectErr *proxyConnectHTTPError
	var dnsErr *net.DNSError
	var errno syscall.Errno
	var certErr *tls.CertificateVerificationError
	var unknownAuthority x509.UnknownAuthorityError
	var hostnameErr x509.HostnameError
	var netErr net.Error
	switch {
	// The account's problems first: their errors may wrap the network
	// error that a renewal also met.
	case errors.Is(err, fxa.ErrReauthRequired):
		return FailureSignIn
	case errors.Is(err, guardian.ErrQuotaExceeded):
		return FailureQuota
	// Guardian's 403 also reads as an invalid token.
	case errors.Is(err, guardian.ErrNotEntitled):
		return FailureNotEntitled
	case errors.Is(err, guardian.ErrTokenInvalid):
		return FailureSignIn
	case errors.Is(err, guardian.ErrRegionUnavailable):
		return FailureRegion
	case errors.As(err, &noAccount):
		return FailureNoAccount
	case errors.Is(err, guardian.ErrServer):
		return FailureServer
	case errors.As(err, &locationErr):
		return FailureLocationRefused
	// A rebuild that waits carries its cause, which decides.
	case errors.As(err, &connectErr):
		return FailureRefused
	case errors.As(err, &dnsErr):
		return FailureNoNetwork
	case errors.As(err, &errno) && slices.Contains(noNetworkErrnos, errno):
		return FailureNoNetwork
	case errors.As(err, &errno) && slices.Contains(cutErrnos, errno),
		errors.As(err, &certErr), errors.As(err, &unknownAuthority), errors.As(err, &hostnameErr),
		errors.Is(err, io.EOF), errors.Is(err, io.ErrUnexpectedEOF),
		errors.Is(err, context.DeadlineExceeded),
		errors.As(err, &netErr) && netErr.Timeout():
		return FailureUnreachable
	}
	return FailureOther
}

// LocationRefusedError is a CONNECT refusal (403 or 407) by the server of a
// location the user chose, with a proxy pass fetched after the first
// refusal: a new pass did not help, so Mozilla most likely does not let
// this account use the location.
type LocationRefusedError struct {
	Err error
}

const locationRefusedText = "Mozilla does not let this account use this location"

func (e *LocationRefusedError) Error() string {
	return locationRefusedText + ": " + e.Err.Error()
}

func (e *LocationRefusedError) Unwrap() error { return e.Err }

// Redacted is the error without the response body, for logs that are not
// verbose.
func (e *LocationRefusedError) Redacted() string {
	var connectErr *proxyConnectHTTPError
	if errors.As(e.Err, &connectErr) {
		return locationRefusedText + ": " + connectErr.Redacted()
	}
	return e.Error()
}

// SessionReplaced reports an error text of a request whose upstream
// session was closed under it because another replaced it (Go's HTTP/2
// client says "client connection force closed").
func SessionReplaced(text string) bool {
	return strings.Contains(text, "client connection force closed") || strings.Contains(text, "use of closed network connection")
}
