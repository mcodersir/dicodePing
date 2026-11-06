package egress

import (
	"testing"
	"time"
)

// This program's own connections are noted by address for a few seconds;
// a client's direct connection is not.
func TestOwnConnectionsAreNoted(t *testing.T) {
	ClearTun()
	now := time.Unix(1000, 0)
	old := ownNow
	ownNow = func() time.Time { return now }
	t.Cleanup(func() { ownNow = old })

	if err := Dialer(0).Control("tcp4", "203.0.113.5:443", nil); err != nil {
		t.Fatal(err)
	}
	if err := ClientDialer(0).Control("tcp4", "203.0.113.6:443", nil); err != nil {
		t.Fatal(err)
	}
	if err := Dialer(0).Control("tcp6", "[::ffff:203.0.113.7]:443", nil); err != nil {
		t.Fatal(err)
	}
	for target, want := range map[string]bool{
		"203.0.113.5:443": true,
		"203.0.113.5:80":  false,
		"203.0.113.6:443": false, // a client's
		"203.0.113.7:443": true,  // the same address, mapped into IPv6
	} {
		if got := OwnDial(target); got != want {
			t.Errorf("OwnDial(%s) = %t", target, got)
		}
	}
	now = now.Add(ownWindow + time.Second)
	if OwnDial("203.0.113.5:443") {
		t.Fatal("an own address is remembered too long")
	}
}

// Loopback never leaves this computer, so it is never noted.
func TestLoopbackIsNotNotedAsOwn(t *testing.T) {
	ClearTun()
	if err := Dialer(0).Control("tcp4", "127.0.0.1:10810", nil); err != nil {
		t.Fatal(err)
	}
	if OwnDial("127.0.0.1:10810") || OwnDial("localhost:10810") {
		t.Fatal("loopback was noted as an own address")
	}
}
