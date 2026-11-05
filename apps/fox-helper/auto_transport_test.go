//go:build with_utls && with_quic

package main

import (
	"context"
	"errors"
	"reflect"
	"testing"
)

func TestAutomaticTransportSelectionUsesOnlyValidatedRelay(t *testing.T) {
	for _, tc := range []struct {
		name     string
		working  int
		terminal bool
		want     []int
	}{
		{"h2", 2, false, []int{2}},
		{"h3 after h2 fails", 3, false, []int{2, 3}},
		{"neither", 0, false, []int{2, 3}},
		{"auth stops fallback", 0, true, []int{2}},
	} {
		t.Run(tc.name, func(t *testing.T) {
			p := newProvider(State{})
			p.pass = "fixture-pass"
			p.selected = Location{Host: "localhost", Port: 443}
			defer p.closeRelays()
			var tried []int
			ok, err := p.probeTransports(context.Background(), func(context.Context) (bool, error) {
				tried = append(tried, p.engine.version)
				if tc.terminal {
					return false, &ProviderError{Code: "login_required"}
				}
				if p.engine.version == tc.working {
					return true, nil
				}
				return false, errors.New("transport unavailable")
			})
			if !reflect.DeepEqual(tried, tc.want) || ok != (tc.working != 0) {
				t.Fatalf("tried=%v success=%v error=%v", tried, ok, err)
			}
			if ok && (p.engine == nil || p.engine.version != tc.working) {
				t.Fatal("validated transport was not retained")
			}
			if !ok && p.engine != nil {
				t.Fatal("failed transport was retained")
			}
		})
	}
}
