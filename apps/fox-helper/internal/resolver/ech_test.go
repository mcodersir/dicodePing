package resolver

import (
	"context"
	"encoding/binary"
	"errors"
	"fmt"
	"io"
	"math/rand/v2"
	"net"
	"net/http"
	"net/http/httptest"
	"testing"

	"golang.org/x/net/dns/dnsmessage"
)

// httpsAnswer replies to query with a CNAME and an HTTPS record carrying
// key (none: a record without ech), or with no record for other names.
func httpsAnswer(t *testing.T, query []byte, key []byte, truncate bool) []byte {
	t.Helper()
	var msg dnsmessage.Message
	if err := msg.Unpack(query); err != nil {
		t.Errorf("bad query: %v", err)
		return nil
	}
	reply := dnsmessage.Message{
		Header:    dnsmessage.Header{ID: msg.Header.ID, Response: true, RecursionAvailable: true, Truncated: truncate},
		Questions: msg.Questions,
	}
	q := msg.Questions[0]
	if q.Type == dnsmessage.TypeHTTPS && q.Name.String() == "relay.example." && !truncate {
		target := dnsmessage.MustNewName("edge.example.")
		var params []dnsmessage.SVCParam
		params = append(params, dnsmessage.SVCParam{Key: dnsmessage.SVCParamALPN, Value: []byte("\x02h2")})
		if key != nil {
			params = append(params, dnsmessage.SVCParam{Key: dnsmessage.SVCParamECH, Value: key})
		}
		reply.Answers = []dnsmessage.Resource{
			{
				Header: dnsmessage.ResourceHeader{Name: q.Name, Type: dnsmessage.TypeCNAME, Class: dnsmessage.ClassINET, TTL: 60},
				Body:   &dnsmessage.CNAMEResource{CNAME: target},
			},
			{
				Header: dnsmessage.ResourceHeader{Name: target, Type: dnsmessage.TypeHTTPS, Class: dnsmessage.ClassINET, TTL: 300},
				Body: &dnsmessage.HTTPSResource{SVCBResource: dnsmessage.SVCBResource{
					Priority: 1, Target: dnsmessage.MustNewName("."), Params: params,
				}},
			},
		}
	}
	packed, err := reply.Pack()
	if err != nil {
		t.Errorf("packing reply: %v", err)
	}
	return packed
}

// startECHDNS serves key over UDP (truncated, so the client asks again
// over TCP, when overTCP) and TCP on one port.
func startECHDNS(t *testing.T, key []byte, overTCP bool) string {
	t.Helper()
	// One port for both, and the system cannot choose it: a port free for one
	// may be reserved for the other (Windows' excluded port ranges, long runs of
	// them side by side, which the ports it hands out in order stay inside).
	var pc net.PacketConn
	var ln net.Listener
	for tries := 0; pc == nil; tries++ {
		address := fmt.Sprintf("127.0.0.1:%d", 20000+rand.IntN(25000))
		var err error
		ln, err = net.Listen("tcp", address)
		if err == nil {
			pc, err = net.ListenPacket("udp", address)
			if err != nil {
				ln.Close()
			}
		}
		if err != nil && tries == 100 {
			t.Fatal(err)
		}
	}
	t.Cleanup(func() { pc.Close() })
	t.Cleanup(func() { ln.Close() })
	go func() {
		buf := make([]byte, 1500)
		for {
			n, addr, err := pc.ReadFrom(buf)
			if err != nil {
				return
			}
			_, _ = pc.WriteTo(httpsAnswer(t, buf[:n], key, overTCP), addr)
		}
	}()
	go func() {
		for {
			conn, err := ln.Accept()
			if err != nil {
				return
			}
			var size [2]byte
			if _, err := io.ReadFull(conn, size[:]); err == nil {
				query := make([]byte, binary.BigEndian.Uint16(size[:]))
				if _, err := io.ReadFull(conn, query); err == nil {
					reply := httpsAnswer(t, query, key, false)
					_, _ = conn.Write(append(binary.BigEndian.AppendUint16(nil, uint16(len(reply))), reply...))
				}
			}
			conn.Close()
		}
	}()
	return pc.LocalAddr().String()
}

func noECHFallback(t *testing.T) {
	old := echFallback
	echFallback = func() []server { return nil }
	t.Cleanup(func() { echFallback = old })
}

// The key comes from the HTTPS record at the end of a CNAME chain, over
// UDP, over TCP when the UDP answer is truncated, and over DNS over HTTPS.
func TestLookupECH(t *testing.T) {
	noECHFallback(t)
	key := []byte{0, 3, 1, 2, 3}
	doh := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		w.Header().Set("Content-Type", dohContentType)
		_, _ = w.Write(httpsAnswer(t, body, key, false))
	}))
	t.Cleanup(doh.Close)
	old := newDoHClient
	newDoHClient = doh.Client
	t.Cleanup(func() { newDoHClient = old })

	for name, spec := range map[string]string{
		"udp":   startECHDNS(t, key, false),
		"tcp":   startECHDNS(t, key, true),
		"https": doh.URL + "/dns-query",
	} {
		r, err := New([]string{spec}, false)
		if err != nil {
			t.Fatal(err)
		}
		got, ttl, err := r.LookupECH(context.Background(), "Relay.Example.")
		if err != nil || string(got) != string(key) || ttl.Seconds() != 300 {
			t.Errorf("%s: key %v ttl %v err %v", name, got, ttl, err)
		}
	}
}

// A record without ech, or no record, is ErrNoECH.
func TestLookupECHWithoutAKey(t *testing.T) {
	noECHFallback(t)
	r, err := New([]string{startECHDNS(t, nil, false)}, false)
	if err != nil {
		t.Fatal(err)
	}
	for _, host := range []string{"relay.example", "other.example"} {
		if _, _, err := r.LookupECH(context.Background(), host); !errors.Is(err, ErrNoECH) {
			t.Errorf("%s: %v", host, err)
		}
	}
}

// The fallback servers are asked too, each server once; with no resolver
// (the system's) only they are.
func TestECHServersAddTheFallbackOnes(t *testing.T) {
	r, err := New([]string{"udp://1.1.1.1", "9.9.9.9"}, false)
	if err != nil {
		t.Fatal(err)
	}
	var names []string
	for _, s := range r.echServers() {
		names = append(names, s.String())
	}
	want := []string{"1.1.1.1", "9.9.9.9", "https://1.1.1.1/dns-query", "https://8.8.8.8/dns-query", "8.8.8.8"}
	if len(names) != len(want) {
		t.Fatalf("got %v, want %v", names, want)
	}
	for i := range want {
		if names[i] != want[i] {
			t.Fatalf("got %v, want %v", names, want)
		}
	}
	if n := len((*Resolver)(nil).echServers()); n != len(echFallbackSpecs) {
		t.Fatalf("the system resolver asks %d servers", n)
	}
}
