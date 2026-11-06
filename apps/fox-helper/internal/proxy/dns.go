package proxy

import (
	"context"
	"encoding/binary"
	"errors"
	"io"
	"net"
	"time"

	"golang.org/x/net/dns/dnsmessage"

	"dicodeping/fox/internal/logx"
)

// DNSPort is DNS's port, which Mozilla's proxy does not connect to. A
// client's DNS sent through the proxy over TCP (PassWall2's remote DNS,
// v2rayN's and Clash's DNS through a SOCKS outbound) is therefore answered
// here: each query goes, as it is, to DNS over HTTPS through Mozilla, and
// the answer comes back to the client (RoutedOpener).
const DNSPort = "53"

// dnsIdle ends a client's DNS connection that long after its last query;
// dnsQueryTimeout bounds the answer to one query.
const (
	dnsIdle         = 30 * time.Second
	dnsQueryTimeout = 10 * time.Second
)

// ExchangeFunc sends a DNS query in wire format and returns the answer.
type ExchangeFunc func(ctx context.Context, query []byte) ([]byte, error)

// serveDNS answers DNS over TCP on conn (RFC 1035 4.2.2: each message after
// its length in two bytes), one query after the other, until the client
// closes it or stays idle. A query that cannot be answered gets SERVFAIL;
// what is not a DNS query ends the connection.
func serveDNS(conn net.Conn, exchange ExchangeFunc) {
	defer conn.Close()
	for {
		_ = conn.SetReadDeadline(time.Now().Add(dnsIdle))
		var size [2]byte
		if _, err := io.ReadFull(conn, size[:]); err != nil {
			return
		}
		query := make([]byte, binary.BigEndian.Uint16(size[:]))
		if _, err := io.ReadFull(conn, query); err != nil {
			return
		}
		answer, err := dnsAnswer(query, exchange)
		if err != nil {
			logx.Debug("DNS through the proxy: %s", logx.Err(err))
			return
		}
		_ = conn.SetWriteDeadline(time.Now().Add(dnsIdle))
		binary.BigEndian.PutUint16(size[:], uint16(len(answer)))
		if _, err := conn.Write(append(size[:], answer...)); err != nil {
			return
		}
	}
}

// dnsAnswer is the answer to one query: the DNS server's, else SERVFAIL.
func dnsAnswer(query []byte, exchange ExchangeFunc) ([]byte, error) {
	var p dnsmessage.Parser
	header, err := p.Start(query)
	if err != nil || header.Response {
		return nil, errors.New("not a DNS query")
	}
	ctx, cancel := context.WithTimeout(context.Background(), dnsQueryTimeout)
	defer cancel()
	answer, err := exchange(ctx, query)
	if err == nil && len(answer) > 0 && len(answer) <= 0xffff {
		return answer, nil
	}
	if err == nil {
		err = errors.New("an empty or oversized answer")
	}
	logx.Debug("a DNS query through the proxy failed; answering SERVFAIL err=%s", logx.Err(err))
	questions, _ := p.AllQuestions()
	return (&dnsmessage.Message{
		Header: dnsmessage.Header{
			ID: header.ID, Response: true, OpCode: header.OpCode,
			RecursionDesired: header.RecursionDesired, RecursionAvailable: true,
			RCode: dnsmessage.RCodeServerFailure,
		},
		Questions: questions,
	}).Pack()
}
