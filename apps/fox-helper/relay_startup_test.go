package main

import "testing"

func TestRecommendedRouteDoesNotWaitForTheCountryCatalog(t *testing.T) {
	calls := 0
	catalog := func() ([]Location, error) { calls++; return []Location{{CountryCode: "DE"}}, nil }
	selected, err := initialRelayLocations("REC", catalog)
	if err != nil || calls != 0 || len(selected) != 1 || selected[0].Host != "p.m1.fastly-masque.net" {
		t.Fatal(selected, err, calls)
	}
	selected, err = initialRelayLocations("DE", catalog)
	if err != nil || calls != 1 || selected[0].CountryCode != "DE" {
		t.Fatal(selected, err, calls)
	}
}
