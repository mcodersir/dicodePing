package resolver

import (
	"context"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"sync/atomic"
	"testing"

	"golang.org/x/net/dns/dnsmessage"
)

// NewThrough asks its servers over the connections dial opens (tunnels
// through Mozilla in the program), caches the answer, and never falls
// back to the system resolver.
func TestThroughUsesDialAndNoSystemFallback(t *testing.T) {
	var hits atomic.Int32
	srv := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		hits.Add(1)
		body, _ := io.ReadAll(r.Body)
		w.Header().Set("Content-Type", dohContentType)
		_, _ = w.Write(answerFor(t, body, [4]byte{93, 184, 215, 14}, 120))
	}))
	defer srv.Close()

	oldServers, oldClient := ThroughServers, throughClient
	t.Cleanup(func() { ThroughServers, throughClient = oldServers, oldClient })
	ThroughServers = []string{"https://dns.invalid/dns-query"}
	var dialed atomic.Int32
	var dialedTo atomic.Value
	throughClient = func(dial DialFunc) *http.Client {
		client := srv.Client()
		transport := client.Transport.(*http.Transport).Clone()
		transport.DialContext = dial
		transport.TLSClientConfig.ServerName = "example.com" // httptest's certificate
		client.Transport = transport
		return client
	}
	r := NewThrough(func(ctx context.Context, network, address string) (net.Conn, error) {
		dialed.Add(1)
		dialedTo.Store(address)
		var d net.Dialer
		return d.DialContext(ctx, "tcp", srv.Listener.Addr().String())
	})

	res, err := r.Lookup(context.Background(), "blocked.example")
	if err != nil || len(res.Addrs) != 1 || res.Addrs[0].String() != "93.184.215.14" {
		t.Fatalf("lookup: %+v %v", res, err)
	}
	if dialed.Load() == 0 || dialedTo.Load() != "dns.invalid:443" {
		t.Fatalf("the query must use dial for the server's address: %d %v", dialed.Load(), dialedTo.Load())
	}
	if again, err := r.Lookup(context.Background(), "blocked.example"); err != nil || !again.Cached || hits.Load() != 1 {
		t.Fatalf("second lookup: %+v %v hits=%d", again, err, hits.Load())
	}

	failing := NewThrough(func(context.Context, string, string) (net.Conn, error) {
		return nil, io.ErrUnexpectedEOF
	})
	if res, err := failing.Lookup(context.Background(), "localhost.example"); err == nil {
		t.Fatalf("a failed query must not fall back to the system resolver: %+v", res)
	}
}

// Exchange passes a client's whole DNS message, of any type, to DNS over
// HTTPS through dial and returns the answer unchanged.
func TestExchangePassesTheMessageAsItIs(t *testing.T) {
	var got atomic.Value
	srv := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		got.Store(body)
		w.Header().Set("Content-Type", dohContentType)
		_, _ = w.Write(append([]byte("answer:"), body...))
	}))
	defer srv.Close()

	oldServers, oldClient := ThroughServers, throughClient
	t.Cleanup(func() { ThroughServers, throughClient = oldServers, oldClient })
	ThroughServers = []string{"https://dns.invalid/dns-query"}
	throughClient = func(dial DialFunc) *http.Client {
		client := srv.Client()
		transport := client.Transport.(*http.Transport).Clone()
		transport.DialContext = dial
		transport.TLSClientConfig.ServerName = "example.com" // httptest's certificate
		client.Transport = transport
		return client
	}
	r := NewThrough(func(ctx context.Context, network, address string) (net.Conn, error) {
		var d net.Dialer
		return d.DialContext(ctx, "tcp", srv.Listener.Addr().String())
	})

	name, _ := dnsmessage.NewName("example.com.")
	query, err := (&dnsmessage.Message{
		Header:    dnsmessage.Header{ID: 4242, RecursionDesired: true},
		Questions: []dnsmessage.Question{{Name: name, Type: dnsmessage.TypeMX, Class: dnsmessage.ClassINET}},
	}).Pack()
	if err != nil {
		t.Fatal(err)
	}
	answer, err := r.Exchange(context.Background(), query)
	if err != nil {
		t.Fatal(err)
	}
	if string(got.Load().([]byte)) != string(query) || string(answer) != "answer:"+string(query) {
		t.Fatalf("sent %q, answered %q", got.Load(), answer)
	}

	// Only DNS over HTTPS can carry a whole message.
	plain, err := New([]string{"udp://9.9.9.9"}, false)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := plain.Exchange(context.Background(), query); err == nil {
		t.Fatal("a resolver without DNS over HTTPS exchanged a message")
	}
}
