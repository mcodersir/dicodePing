// Package netstate tells whether the computer is connected to a network:
// an adapter that is up and has a default gateway (Windows) or a default
// route (Linux). It sends nothing; a network without internet access, or
// behind a captive portal, counts as connected.
package netstate

import "sync/atomic"

// reported is the state the host reported (Report): 0 none, 1 connected,
// 2 not connected.
var reported atomic.Int32

// Report sets the network state from the host, which knows it better: on
// Android apps may not read the route table, so the app reports what
// Android's connectivity service says.
func Report(connected bool) {
	if connected {
		reported.Store(1)
	} else {
		reported.Store(2)
	}
}

// ReportedDown reports whether the host said no network is connected (the
// phone: no Wi-Fi and no mobile data). Only a report counts: the system
// is not asked.
func ReportedDown() bool { return reported.Load() == 2 }

// Connected reports whether a network is connected: as reported, else
// read from the system. When the state cannot be read, and on other
// platforms, it reports true, so a failed check never holds the program
// back.
func Connected() bool {
	switch reported.Load() {
	case 1:
		return true
	case 2:
		return false
	}
	return connected()
}

// Current names the networks this computer is connected to (their
// interfaces, addresses, and gateways), "" for none, so a change can be
// noticed by comparing two readings; ok is false where it cannot be read
// (macOS, Android). It sends nothing.
func Current() (name string, ok bool) { return current() }
