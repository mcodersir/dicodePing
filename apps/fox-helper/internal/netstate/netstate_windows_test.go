//go:build windows

package netstate

import "testing"

// Reads this computer's adapters; the result depends on its network, so
// the test only logs which adapters count.
func TestWindowsAdapters(t *testing.T) {
	list, err := adapters()
	if err != nil {
		t.Fatal(err)
	}
	if len(list) == 0 {
		t.Fatal("no adapters, not even loopback")
	}
	for _, a := range list {
		t.Logf("%-40s up=%-5t gateway=%-5t loopback=%t", a.name, a.up, a.gateway, a.loopback)
	}
	t.Logf("connected=%t", Connected())
}
