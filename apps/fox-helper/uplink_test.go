package main

import "testing"

func TestUnknownUplinkFailsInsteadOfSilentlyUsingAnotherVpn(t *testing.T) {
	p := newProvider(State{})
	if p.bindUplink("DicodePing_interface_that_does_not_exist") == nil {
		t.Fatal("unknown interface accepted")
	}
	if p.bindUplink("") != nil {
		t.Fatal("default uplink rejected")
	}
}
