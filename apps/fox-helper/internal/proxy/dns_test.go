package proxy

import (
	"context"
	"encoding/binary"
	"errors"
	"io"
	"net"
	"slices"
	"sync"
	"testing"
	"time"

	"golang.org/x/net/dns/dnsmessage"

	"dicodeping/fox/internal/routing"
)

func dnsQuery(t *testing.T, id uint16, host string, qtype dnsmessage.Type) []byte {
	t.Helper()
	name, err := dnsmessage.NewName(host + ".")
	if err != nil {
		t.Fatal(err)
	}
	msg, err := (&dnsmessage.Message{
		Header:    dnsmessage.Header{ID: id, RecursionDesired: true},
		Questions: []dnsmessage.Question{{Name: name, Type: qtype, Class: dnsmessage.ClassINET}},
	}).Pack()
	if err != nil {
		t.Fatal(err)
	}
	return msg
}

// askDNS sends one message over DNS over TCP and reads the answer.
func askDNS(t *testing.T, conn net.Conn, msg []byte) []byte {
	t.Helper()
	_ = conn.SetDeadline(time.Now().Add(5 * time.Second))
	framed := binary.BigEndian.AppendUint16(nil, uint16(len(msg)))
	if _, err := conn.Write(append(framed, msg...)); err != nil {
		t.Fatal(err)
	}
	var size [2]byte
	if _, err := io.ReadFull(conn, size[:]); err != nil {
		t.Fatal(err)
	}
	answer := make([]byte, binary.BigEndian.Uint16(size[:]))
	if _, err := io.ReadFull(conn, answer); err != nil {
		t.Fatal(err)
	}
	return answer
}

// DNS sent through the proxy goes to DNS over HTTPS (exchange), never to
// Mozilla's port 53, which it refuses: queries of any type, several over
// one connection, get the DNS server's answers as they are.
func TestDNSThroughTheProxyIsAnsweredHere(t *testing.T) {
	t.Parallel()

	upstream := &recordingOpener{}
	routed := NewRoutedOpener(upstream)
	defer routed.Close()
	var mu sync.Mutex
	var asked [][]byte
	routed.exchange = func(_ context.Context, query []byte) ([]byte, error) {
		mu.Lock()
		asked = append(asked, query)
		mu.Unlock()
		return append([]byte("answer:"), query...), nil
	}

	conn, err := routed.OpenTunnelForClient("1.1.1.1:53", "192.168.1.20")
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close()
	for i, qtype := range []dnsmessage.Type{dnsmessage.TypeA, dnsmessage.TypeMX} {
		query := dnsQuery(t, uint16(100+i), "example.com", qtype)
		if got := askDNS(t, conn, query); string(got) != "answer:"+string(query) {
			t.Fatalf("answer %q", got)
		}
	}
	mu.Lock()
	n := len(asked)
	mu.Unlock()
	upstream.mu.Lock()
	targets := slices.Clone(upstream.targets)
	upstream.mu.Unlock()
	if n != 2 || slices.Contains(targets, "1.1.1.1:53") {
		t.Fatalf("queries asked %d, tunnels %v", n, targets)
	}
	if c := routed.Counts(); c.Proxy != 1 {
		t.Fatalf("counts %+v", c)
	}
}

// A query the DNS servers do not answer gets SERVFAIL for the same ID and
// question, so the client tries again or reports it at once; what is not
// a DNS query ends the connection.
func TestAFailedDNSQueryGetsServfail(t *testing.T) {
	t.Parallel()

	client, server := net.Pipe()
	defer client.Close()
	go serveDNS(server, func(context.Context, []byte) ([]byte, error) {
		return nil, errors.New("no DNS server answered")
	})
	answer := askDNS(t, client, dnsQuery(t, 7, "example.com", dnsmessage.TypeAAAA))
	var msg dnsmessage.Message
	if err := msg.Unpack(answer); err != nil {
		t.Fatal(err)
	}
	if !msg.Response || msg.ID != 7 || msg.RCode != dnsmessage.RCodeServerFailure ||
		len(msg.Questions) != 1 || msg.Questions[0].Type != dnsmessage.TypeAAAA {
		t.Fatalf("answer %+v", msg)
	}

	// An answer sent as a query is no query.
	notQuery, _ := (&dnsmessage.Message{Header: dnsmessage.Header{ID: 8, Response: true}}).Pack()
	_ = client.SetDeadline(time.Now().Add(5 * time.Second))
	if _, err := client.Write(append(binary.BigEndian.AppendUint16(nil, uint16(len(notQuery))), notQuery...)); err != nil {
		t.Fatal(err)
	}
	if _, err := client.Read(make([]byte, 1)); err == nil {
		t.Fatal("the connection stayed open after a message that is no query")
	}
}

// A routing rule that sends port 53 directly still does: only DNS that
// would go to Mozilla is answered here.
func TestDNSRoutedDirectlyStaysDirect(t *testing.T) {
	t.Parallel()

	routed := NewRoutedOpener(&recordingOpener{})
	defer routed.Close()
	var dialed []string
	routed.dial = func(_ context.Context, _, address string) (net.Conn, error) {
		dialed = append(dialed, address)
		a, b := net.Pipe()
		_ = b.Close()
		return a, nil
	}
	routed.exchange = func(context.Context, []byte) ([]byte, error) {
		t.Error("a direct DNS server was answered here")
		return nil, errors.New("unexpected")
	}
	router, err := routing.New(routing.Config{Direct: []string{"10.0.0.0/8"}})
	if err != nil {
		t.Fatal(err)
	}
	routed.SetRouter(router)
	conn, err := routed.OpenTunnel("10.1.2.3:53")
	if err != nil {
		t.Fatal(err)
	}
	_ = conn.Close()
	if len(dialed) != 1 || dialed[0] != "10.1.2.3:53" {
		t.Fatalf("direct dials %v", dialed)
	}
}
