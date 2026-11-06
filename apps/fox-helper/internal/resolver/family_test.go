package resolver

import (
	"context"
	"net/netip"
	"slices"
	"sync/atomic"
	"testing"
	"time"
)

func TestKeepFamily(t *testing.T) {
	v4 := netip.MustParseAddr("151.101.1.91")
	v6 := netip.MustParseAddr("2a04:4e42::347")
	mapped := netip.MustParseAddr("::ffff:146.75.121.91")
	all := []netip.Addr{v4, v6, mapped}
	for network, want := range map[string][]netip.Addr{
		"tcp":  all,
		"udp":  all,
		"tcp4": {v4, mapped},
		"udp4": {v4, mapped},
		"ip4":  {v4, mapped},
		"tcp6": {v6},
		"udp6": {v6},
		"ip6":  {v6},
	} {
		if got := KeepFamily(network, all); !slices.Equal(got, want) {
			t.Errorf("KeepFamily(%s) = %v, want %v", network, got, want)
		}
	}
}

// The IPv6 addresses are asked for on their own (AAAA) and kept apart in
// the cache from the name's usual answer.
func TestLookupIPv6(t *testing.T) {
	var asked atomic.Int32
	v6 := &fakeServer{addr: "2a04:4e41:8001::17"}
	r := withFakes(v6, "", &asked)
	got, err := r.LookupIPv6(context.Background(), "ehrd229.example")
	if err != nil || len(got.Addrs) != 1 || got.Addrs[0].String() != "2a04:4e41:8001::17" {
		t.Fatalf("LookupIPv6 = %+v, %v", got, err)
	}
	again, err := r.LookupIPv6(context.Background(), "ehrd229.example")
	if err != nil || !again.Cached {
		t.Fatalf("second LookupIPv6 = %+v, %v, want cached", again, err)
	}

	v4 := &fakeServer{addr: "192.0.2.1"}
	r = withFakes(v4, "", &asked)
	r.fallback = false
	if got, err := r.LookupIPv6(context.Background(), "v4only.example"); err == nil {
		t.Fatalf("a name without IPv6 answered %+v", got)
	}
}

// A connection kept to IPv6 fails at once for a name without an IPv6
// address, before any connection is tried.
func TestDialWithoutTheFamilyAsked(t *testing.T) {
	var asked atomic.Int32
	r := withFakes(&fakeServer{addr: "192.0.2.1"}, "", &asked)
	r.fallback = false
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	if _, err := r.DialContext(ctx, "tcp6", "v4only.example:443"); err == nil {
		t.Fatal("dial tcp6 to a name without IPv6 succeeded")
	}
	if ctx.Err() != nil {
		t.Fatal("dial tcp6 waited for its whole time")
	}
}

func TestInterleave(t *testing.T) {
	a := []netip.Addr{netip.MustParseAddr("192.0.2.1"), netip.MustParseAddr("192.0.2.2"), netip.MustParseAddr("192.0.2.3")}
	b := []netip.Addr{netip.MustParseAddr("2001:db8::1")}
	got := interleave(a, b)
	want := []netip.Addr{a[0], b[0], a[1], a[2]}
	if !slices.Equal(got, want) {
		t.Fatalf("interleave = %v, want %v", got, want)
	}
}

// Dual-stack takes the IPv4 and IPv6 answers together, and is happy with
// either alone.
func TestLookupBoth(t *testing.T) {
	var asked atomic.Int32
	r := withFakes(&fakeServer{addr: "2a04:4e41:8001::17"}, "", &asked)
	r.fallback = false
	got, err := r.lookupBoth(context.Background(), "v6.example")
	if err != nil || len(got) != 1 || !got[0].Is6() {
		t.Fatalf("lookupBoth = %v, %v", got, err)
	}
	r = withFakes(&fakeServer{addr: "192.0.2.1"}, "", &asked)
	r.fallback = false
	got, err = r.lookupBoth(context.Background(), "v4.example")
	if err != nil || len(got) != 1 || !got[0].Is4() {
		t.Fatalf("lookupBoth = %v, %v", got, err)
	}
}
