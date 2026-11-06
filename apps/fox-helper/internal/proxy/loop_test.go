package proxy

import (
	"net"
	"testing"
	"time"

	"dicodeping/fox/internal/egress"
)

// One own address coming back is chance; two different ones within the
// window are a loop, warned of once a minute.
func TestLoopWatchNeedsTwoOwnAddresses(t *testing.T) {
	t.Parallel()

	var w loopWatch
	now := time.Unix(1000, 0)
	if loop, _ := w.note("1.1.1.1:443", now); loop {
		t.Fatal("one address made a loop")
	}
	if loop, _ := w.note("1.1.1.1:443", now.Add(time.Second)); loop {
		t.Fatal("the same address again made a loop")
	}
	if loop, warn := w.note("8.8.8.8:443", now.Add(2*time.Second)); !loop || !warn {
		t.Fatalf("two addresses: loop %t, warn %t", loop, warn)
	}
	if loop, warn := w.note("9.9.9.9:443", now.Add(3*time.Second)); !loop || warn {
		t.Fatalf("again within a minute: loop %t, warn %t", loop, warn)
	}
	later := now.Add(loopWindow + 10*time.Second)
	if loop, _ := w.note("1.1.1.1:443", later); loop {
		t.Fatal("old addresses still counted")
	}
}

// This program's own connections coming back through a client make a
// notice for the dashboard.
func TestALoopMakesANotice(t *testing.T) {
	loops = loopWatch{}
	t.Cleanup(func() { loops = loopWatch{} })
	for _, own := range []string{"203.0.113.21:443", "203.0.113.22:443"} {
		if err := egress.Dialer(0).Control("tcp4", own, nil); err != nil {
			t.Fatal(err)
		}
	}
	s := &SOCKSServer{upstream: &recordingOpener{}, Notices: &Notices{}}
	client, other := net.Pipe()
	defer client.Close()
	defer other.Close()
	for _, target := range []string{"203.0.113.21:443", "203.0.113.22:443"} {
		_, _ = s.openTarget(client, target, "127.0.0.1:40000", "socks5")
	}
	notices := s.Notices.Since(time.Time{})
	if len(notices) != 1 || notices[0].Kind != NoticeLoop || notices[0].Count != 1 {
		t.Fatalf("notices %+v", notices)
	}
	// A client's connection to an address this program never used is no
	// loop.
	loops = loopWatch{}
	s2 := &SOCKSServer{upstream: &recordingOpener{}, Notices: &Notices{}}
	for _, target := range []string{"198.51.100.1:443", "198.51.100.2:443"} {
		_, _ = s2.openTarget(client, target, "127.0.0.1:40000", "socks5")
	}
	for _, n := range s2.Notices.Since(time.Time{}) {
		if n.Kind == NoticeLoop {
			t.Fatalf("a loop without own connections: %+v", n)
		}
	}
}
