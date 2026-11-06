package resolver

import (
	"context"
	"errors"
	"net"
	"net/netip"
	"sync/atomic"
	"testing"
	"time"
)

// An address that never answers (as some of Fastly's do from Iran) costs a
// short wait, not the whole timeout: the next address is tried after the
// stagger and its connection is used.
func TestDialRacePassesAnAddressThatDoesNotAnswer(t *testing.T) {
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer ln.Close()
	_, port, _ := net.SplitHostPort(ln.Addr().String())

	dead := netip.MustParseAddr("198.51.100.7")
	var deadEnded atomic.Bool
	dial := func(ctx context.Context, network, address string) (net.Conn, error) {
		if address == net.JoinHostPort(dead.String(), port) {
			<-ctx.Done()
			deadEnded.Store(true)
			return nil, ctx.Err()
		}
		return (&net.Dialer{}).DialContext(ctx, network, address)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	start := time.Now()
	conn, err := dialRace(ctx, dial, "tcp", port, []netip.Addr{dead, netip.MustParseAddr("127.0.0.1")}, 50*time.Millisecond)
	if err != nil {
		t.Fatal(err)
	}
	conn.Close()
	if took := time.Since(start); took > 2*time.Second {
		t.Fatalf("connected after %s", took)
	}
	deadline := time.Now().Add(2 * time.Second)
	for !deadEnded.Load() && time.Now().Before(deadline) {
		time.Sleep(10 * time.Millisecond)
	}
	if !deadEnded.Load() {
		t.Fatal("the attempt on the silent address was not cancelled")
	}
}

// An address that refused goes to the end of the list for the next
// connection; one that connects again comes back.
func TestFailedAddressGoesLast(t *testing.T) {
	bad := netip.MustParseAddr("198.51.100.8")
	good := netip.MustParseAddr("198.51.100.9")
	refused := errors.New("refused")
	dial := func(ctx context.Context, network, address string) (net.Conn, error) {
		if address == net.JoinHostPort(bad.String(), "443") {
			return nil, refused
		}
		c1, c2 := net.Pipe()
		c2.Close()
		return c1, nil
	}
	conn, err := dialRace(context.Background(), dial, "tcp", "443", []netip.Addr{bad, good}, time.Second)
	if err != nil {
		t.Fatal(err)
	}
	conn.Close()
	if got := orderAddrs([]netip.Addr{bad, good}); got[0] != good {
		t.Fatalf("order after a failure: %v", got)
	}
	failedAddrs.Delete(bad)
	if got := orderAddrs([]netip.Addr{bad, good}); got[0] != bad {
		t.Fatalf("order once it expired: %v", got)
	}
}

// When every address fails, the last error is given.
func TestDialRaceAllFail(t *testing.T) {
	refused := errors.New("refused")
	dial := func(context.Context, string, string) (net.Conn, error) { return nil, refused }
	_, err := dialRace(context.Background(), dial, "tcp", "443",
		[]netip.Addr{netip.MustParseAddr("198.51.100.10"), netip.MustParseAddr("198.51.100.11")}, time.Second)
	if !errors.Is(err, refused) {
		t.Fatalf("err = %v", err)
	}
}
