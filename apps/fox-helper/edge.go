package main

// Secure edge bootstrap follows the v1.0.7 reference: DNS-over-HTTPS may
// supply the address, while the original relay name remains the TLS identity.
import (
	"bytes"
	"context"
	"crypto/rand"
	"crypto/tls"
	"encoding/binary"
	"errors"
	"io"
	"net"
	"net/http"
	"strings"
	"time"
)

type edgeCacheEntry struct {
	addresses []net.IP
	expires   time.Time
}

func dnsQuestion(host string) ([]byte, error) {
	packet := make([]byte, 12)
	if _, err := rand.Read(packet[:2]); err != nil {
		return nil, err
	}
	packet[2] = 1
	packet[5] = 1
	for _, label := range strings.Split(strings.TrimSuffix(host, "."), ".") {
		if len(label) == 0 || len(label) > 63 {
			return nil, errors.New("invalid DNS name")
		}
		packet = append(packet, byte(len(label)))
		packet = append(packet, label...)
	}
	if len(packet) > 266 {
		return nil, errors.New("DNS name too long")
	}
	return append(packet, 0, 0, 1, 0, 1), nil
}

func skipDNSName(packet []byte, offset int) (int, error) {
	for count := 0; count < 128 && offset < len(packet); count++ {
		size := int(packet[offset])
		offset++
		if size == 0 {
			return offset, nil
		}
		if size&0xc0 == 0xc0 {
			if offset >= len(packet) {
				break
			}
			pointer := (size&0x3f)<<8 | int(packet[offset])
			if pointer >= len(packet) {
				break
			}
			return offset + 1, nil
		}
		if size > 63 || offset+size > len(packet) {
			break
		}
		offset += size
	}
	return 0, errors.New("malformed DNS name")
}

func dnsAddresses(question, packet []byte) ([]net.IP, error) {
	if len(question) < 12 || len(packet) < 12 || !bytes.Equal(question[:2], packet[:2]) || packet[2]&0x80 == 0 || packet[2]&2 != 0 || packet[3]&15 != 0 {
		return nil, errors.New("invalid DNS response")
	}
	offset := 12
	for n := int(binary.BigEndian.Uint16(packet[4:6])); n > 0; n-- {
		next, err := skipDNSName(packet, offset)
		if err != nil || next+4 > len(packet) {
			return nil, errors.New("invalid DNS question")
		}
		offset = next + 4
	}
	var result []net.IP
	for n := int(binary.BigEndian.Uint16(packet[6:8])); n > 0; n-- {
		next, err := skipDNSName(packet, offset)
		if err != nil || next+10 > len(packet) {
			return nil, errors.New("invalid DNS answer")
		}
		kind, class, size := binary.BigEndian.Uint16(packet[next:]), binary.BigEndian.Uint16(packet[next+2:]), int(binary.BigEndian.Uint16(packet[next+8:]))
		offset = next + 10
		if offset+size > len(packet) {
			return nil, errors.New("truncated DNS answer")
		}
		if kind == 1 && class == 1 && size == 4 {
			ip := net.IP(append([]byte(nil), packet[offset:offset+size]...))
			if !ip.IsUnspecified() && !ip.IsLoopback() && !ip.IsPrivate() && !ip.IsLinkLocalUnicast() {
				result = append(result, ip)
			}
		}
		offset += size
	}
	if len(result) == 0 {
		return nil, errors.New("DNS returned no public edge address")
	}
	return result, nil
}

func (p *provider) bootstrapEdge(ctx context.Context, host string) ([]net.IP, error) {
	if cached, ok := p.edgeCache.Load(host); ok {
		entry := cached.(edgeCacheEntry)
		if time.Now().Before(entry.expires) {
			return entry.addresses, nil
		}
	}
	question, err := dnsQuestion(host)
	if err != nil {
		return nil, err
	}
	ctx, cancel := context.WithTimeout(ctx, 3*time.Second)
	defer cancel()
	transport := &http.Transport{Proxy: nil, DialContext: p.relayDialer().DialContext, TLSClientConfig: &tls.Config{RootCAs: p.roots, MinVersion: tls.VersionTLS12}}
	defer transport.CloseIdleConnections()
	client := &http.Client{Transport: transport, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	results := make(chan []net.IP, 3)
	for _, endpoint := range []string{"https://9.9.9.9/dns-query", "https://1.1.1.1/dns-query", "https://8.8.8.8/dns-query"} {
		go func(endpoint string) {
			req, _ := http.NewRequestWithContext(ctx, http.MethodPost, endpoint, bytes.NewReader(question))
			req.Header.Set("Content-Type", "application/dns-message")
			req.Header.Set("Accept", "application/dns-message")
			resp, err := client.Do(req)
			if err != nil {
				results <- nil
				return
			}
			defer resp.Body.Close()
			body, err := io.ReadAll(io.LimitReader(resp.Body, 4097))
			if err != nil || len(body) > 4096 || resp.StatusCode != 200 {
				results <- nil
				return
			}
			ips, _ := dnsAddresses(question, body)
			results <- ips
		}(endpoint)
	}
	for range 3 {
		select {
		case ips := <-results:
			if len(ips) > 0 {
				p.edgeCache.Store(host, edgeCacheEntry{ips, time.Now().Add(5 * time.Minute)})
				return ips, nil
			}
		case <-ctx.Done():
			return nil, ctx.Err()
		}
	}
	return nil, errors.New("secure edge DNS unavailable")
}

func (p *provider) dialEdgeTLS(ctx context.Context, network, address string) (net.Conn, error) {
	return p.dialProviderTLS(ctx, network, address, true)
}
func (p *provider) dialControlTLS(ctx context.Context, network, address string) (net.Conn, error) {
	return p.dialProviderTLS(ctx, network, address, false)
}
func (p *provider) dialProviderTLS(ctx context.Context, network, address string, edge bool) (net.Conn, error) {
	host, port, err := net.SplitHostPort(address)
	if err != nil {
		return nil, err
	}
	candidates := []string{}
	if net.ParseIP(host) == nil {
		resolver := p.edgeResolver
		if resolver == nil {
			resolver = p.bootstrapEdge
		}
		if ips, err := resolver(ctx, host); err == nil {
			for _, ip := range ips {
				candidates = append(candidates, net.JoinHostPort(ip.String(), port))
			}
		}
	}
	// The system resolver is a bounded fallback when all DoH endpoints are blocked.
	candidates = append(candidates, address)
	for _, candidate := range candidates {
		attempt, cancel := context.WithTimeout(ctx, 5*time.Second)
		raw, e := p.relayDialer().DialContext(attempt, network, candidate)
		if e == nil {
			protocols := []string{"h2", "http/1.1"}
			if edge {
				protocols = []string{"h2"}
			}
			secure := tls.Client(&helloSplitConn{Conn: raw, mode: p.tlsSplit}, &tls.Config{RootCAs: p.roots, ServerName: host, MinVersion: tls.VersionTLS12, NextProtos: protocols})
			e = secure.HandshakeContext(attempt)
			if e == nil && edge && secure.ConnectionState().NegotiatedProtocol != "h2" {
				e = errors.New("relay did not negotiate HTTP/2")
			}
			if e == nil {
				cancel()
				return secure, nil
			}
			secure.Close()
		}
		cancel()
		err = e
		if ctx.Err() != nil {
			return nil, ctx.Err()
		}
	}
	p.edgeCache.Delete(host)
	return nil, err
}
