package main

import (
	"context"
	"errors"
	"net"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/sagernet/sing-box/log"
	"github.com/sagernet/sing-box/option"
	singHTTP "github.com/sagernet/sing-box/transport/http"
	"github.com/sagernet/sing/common/json/badoption"
	M "github.com/sagernet/sing/common/metadata"
)

// Each helper process owns one account. Bearer rotation updates new CONNECT
// requests without closing transports carrying established application streams.
type singRelay struct {
	client *singHTTP.Client
}

type singUplink struct{ p *provider }

func (d singUplink) DialContext(ctx context.Context, network string, destination M.Socksaddr) (net.Conn, error) {
	address := destination.String()
	if destination.IsFqdn() {
		resolver := d.p.edgeResolver
		if resolver == nil {
			resolver = d.p.bootstrapEdge
		}
		if ips, err := resolver(ctx, destination.Fqdn); err == nil {
			for _, ip := range ips {
				attempt, cancel := context.WithTimeout(ctx, 5*time.Second)
				conn, err := d.p.relayDialer().DialContext(attempt, network, net.JoinHostPort(ip.String(), strconv.Itoa(int(destination.Port))))
				cancel()
				if err == nil {
					return conn, nil
				}
				if ctx.Err() != nil {
					return nil, ctx.Err()
				}
			}
		}
	}
	return d.p.relayDialer().DialContext(ctx, network, address)
}

func (d singUplink) ListenPacket(ctx context.Context, destination M.Socksaddr) (net.PacketConn, error) {
	// H2 CONNECT uses TCP. Do not accidentally create an unbound UDP socket
	// outside the Android/Windows physical-interface protection contract.
	return nil, errors.New("raw UDP uplink is unavailable; use HTTP/2")
}

func (p *provider) newSingRelay() (*singRelay, error) {
	singHTTP.SetDynamicBearerToken(p.pass)
	enabled := true
	bearer, err := singHTTP.AcquireBearerTokenProvider(nil, &enabled)
	if err != nil {
		return nil, err
	}
	tls := option.OutboundTLSOptions{
		Enabled: true, ServerName: p.selected.Host,
		UTLS:           &option.OutboundUTLSOptions{Enabled: true, Fingerprint: "chrome"},
		RecordFragment: p.tlsSplit != "off",
	}
	if p.rootPEM != "" {
		tls.Certificate = []string{p.rootPEM}
	}
	version := p.httpVersion
	if version == 0 {
		version = 2
	}
	if version == 3 {
		// QUIC uses Go TLS, not the TCP uTLS handshake adapter. Keeping
		// uTLS enabled here makes every H3 connection fail before sending UDP.
		tls.UTLS = nil
		tls.RecordFragment = false
	}
	client, err := singHTTP.NewClientWithTLS(context.Background(), log.NewNOPFactory().Logger(), singUplink{p},
		option.ServerOptions{Server: p.selected.Host, ServerPort: uint16(p.selected.Port)}, tls,
		singHTTP.ClientOptions{Version: version, DisableVersionFallback: true, BearerToken: bearer,
			HTTP2Options: option.HTTP2Options{IdleTimeout: badoption.Duration(30 * time.Second), KeepAlivePeriod: badoption.Duration(15 * time.Second)},
			Headers:      http.Header{"User-Agent": []string{userAgent}}})
	if err != nil {
		return nil, err
	}
	return &singRelay{client: client}, nil
}

func (r *singRelay) Close() {
	_ = r.client.Close()
	singHTTP.SetDynamicBearerToken("")
}

func (p *provider) openSingTunnel(ctx context.Context, authority string) (net.Conn, error) {
	if p.engine == nil {
		return nil, errors.New("Fox sing-box transport is not initialized")
	}
	pass, err := p.proxyPass(ctx)
	if err != nil {
		return nil, err
	}
	p.syncSingToken()
	conn, err := p.engine.client.DialContext(ctx, "tcp", M.ParseSocksaddr(authority))
	if err == nil {
		return conn, nil
	}
	// The pinned fork reports HTTP 407 with this stable error. Refresh once,
	// and never retry after application bytes have been sent.
	if !strings.Contains(err.Error(), "authentication required") && !strings.Contains(err.Error(), "401 Unauthorized") {
		return nil, p.singRelayError(err)
	}
	p.mutex.Lock()
	if p.pass == pass {
		p.pass = ""
		p.passExpiry = 0
	}
	p.mutex.Unlock()
	// proxyPass shares the existing cancellable refresh gate. Concurrent
	// rejections renew once; short-lived callers can leave while renewal runs.
	_, err = p.proxyPass(ctx)
	if err != nil {
		return nil, err
	}
	p.syncSingToken()
	conn, err = p.engine.client.DialContext(ctx, "tcp", M.ParseSocksaddr(authority))
	if err != nil && (strings.Contains(err.Error(), "authentication required") || strings.Contains(err.Error(), "401 Unauthorized")) {
		return nil, &ProviderError{Code: "login_required", Message: "The proxy pass was rejected; sign in again"}
	}
	return conn, p.singRelayError(err)
}

func (p *provider) singRelayError(err error) error {
	if err == nil || !strings.Contains(err.Error(), "429 ") {
		return err
	}
	p.mutex.Lock()
	exhausted := p.info.QuotaRemaining != nil && *p.info.QuotaRemaining <= 0
	p.mutex.Unlock()
	if exhausted {
		return &ProviderError{Code: "quota_exceeded", Status: 429, Message: "The provider reports no remaining VPN allowance"}
	}
	return proxyLimitError(nil)
}

func (p *provider) syncSingToken() {
	p.mutex.Lock()
	defer p.mutex.Unlock()
	singHTTP.SetDynamicBearerToken(p.pass)
}
