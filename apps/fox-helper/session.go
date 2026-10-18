package main

import (
	"context"
	"crypto/tls"
	"net/http"
	"time"
)

// IdleConnTimeout does not check HTTP/2 connections with active CONNECT
// streams. Ping a silent edge and close a transport that no longer responds,
// so new streams can obtain a new connection instead of sharing a dead socket.
func relayHTTP2Config() *http.HTTP2Config {
	return &http.HTTP2Config{SendPingTimeout: 15 * time.Second, PingTimeout: 10 * time.Second, WriteByteTimeout: 15 * time.Second}
}

func (p *provider) proxyPass(ctx context.Context) (string, error) {
	p.mutex.Lock()
	pass, expiry := p.pass, p.passExpiry
	exhausted := p.info.QuotaRemaining != nil && *p.info.QuotaRemaining <= 0
	p.mutex.Unlock()
	if !exhausted && pass != "" && expiry > time.Now().Unix() {
		return pass, nil
	}
	if err := p.refreshProxyPass(ctx, false); err != nil {
		return "", err
	}
	p.mutex.Lock()
	defer p.mutex.Unlock()
	return p.pass, nil
}

// Refresh on a private snapshot: slow Guardian/auth requests must never hold
// the mutex needed by every new SOCKS connection or invalidate a working pass.
// Only one refresh runs at a time; waiters remain cancellable.
func (p *provider) refreshProxyPass(ctx context.Context, force bool) error {
	select {
	case p.passRefresh <- struct{}{}:
	case <-ctx.Done():
		return ctx.Err()
	}
	defer func() { <-p.passRefresh }()
	p.mutex.Lock()
	if !force && p.pass != "" && p.passExpiry > time.Now().Unix() && (p.info.QuotaRemaining == nil || *p.info.QuotaRemaining > 0) {
		p.mutex.Unlock()
		return nil
	}
	snapshot := &provider{state: p.state, info: p.info, client: p.client, authURL: p.authURL, guardianURL: p.guardianURL, settingsURL: p.settingsURL}
	oldState := p.state
	p.mutex.Unlock()
	ctx, cancel := context.WithTimeout(ctx, 15*time.Second)
	defer cancel()
	pass, err := snapshot.proxyPassLocked(ctx)
	p.mutex.Lock()
	p.state = snapshot.state
	if err == nil {
		p.pass = pass
		p.passExpiry = snapshot.passExpiry
		p.info = snapshot.info
	}
	// Quota exhaustion is authoritative even when no pass is returned.
	if snapshot.info.QuotaRemaining != nil && *snapshot.info.QuotaRemaining <= 0 {
		p.info = snapshot.info
	}
	state, info := p.state, p.info
	p.mutex.Unlock()
	if state != oldState && p.onState != nil {
		p.onState(state)
	}
	if err == nil && p.onAccount != nil {
		p.onAccount(info)
	}
	return err
}

func (p *provider) relayTransport() *http.Transport {
	return &http.Transport{Proxy: nil, ForceAttemptHTTP2: true, DialContext: p.relayDialer().DialContext, DialTLSContext: p.dialEdgeTLS, TLSClientConfig: &tls.Config{RootCAs: p.roots, MinVersion: tls.VersionTLS12, NextProtos: []string{"h2"}}, TLSHandshakeTimeout: 10 * time.Second, ResponseHeaderTimeout: 12 * time.Second, IdleConnTimeout: 90 * time.Second, HTTP2: relayHTTP2Config()}
}
