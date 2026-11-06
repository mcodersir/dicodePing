package proxy

import (
	"path/filepath"
	"strings"
	"testing"

	"dicodeping/fox/internal/serverlist"
)

func TestNormalizeProxyURLAddsHTTPS(t *testing.T) {
	t.Parallel()

	got, err := NormalizeURL("proxy.example.test:443")
	if err != nil {
		t.Fatalf("normalizeProxyURL returned error: %v", err)
	}

	if got.Scheme != "https" {
		t.Fatalf("expected https scheme, got %q", got.Scheme)
	}
	if got.Host != "proxy.example.test:443" {
		t.Fatalf("expected host proxy.example.test:443, got %q", got.Host)
	}
}

func TestConnectProxyHostsIncludesDefaultConnectServers(t *testing.T) {
	t.Parallel()

	countries := []serverlist.Country{
		{
			Name: "United States",
			Code: "US",
			Cities: []serverlist.City{
				{
					Name: "New York",
					Code: "nyc",
					Servers: []serverlist.Server{
						{Hostname: "default.example", Port: 443},
						{Protocols: []serverlist.Protocol{{Name: "connect", Host: "proto.example", Port: 8443}}},
					},
				},
			},
		},
	}

	got := connectProxyHosts(countries)
	want := []string{"default.example:443", "proto.example:8443"}
	if len(got) != len(want) {
		t.Fatalf("expected %d proxies, got %d: %v", len(want), len(got), got)
	}
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("expected %q at index %d, got %q", want[i], i, got[i])
		}
	}
}

func TestConnectProxyCandidatesIncludeExitMetadata(t *testing.T) {
	t.Parallel()

	countries := []serverlist.Country{
		{
			Name: "Germany",
			Code: "DE",
			Cities: []serverlist.City{
				{
					Name: "Frankfurt",
					Code: "fra",
					Servers: []serverlist.Server{
						{Protocols: []serverlist.Protocol{{Name: "connect", Host: "de.example", Port: 443}}},
					},
				},
			},
		},
	}

	got := ConnectCandidates(countries)
	if len(got) != 1 {
		t.Fatalf("expected 1 candidate, got %d: %v", len(got), got)
	}
	candidate := got[0]
	if candidate.Addr != "de.example:443" {
		t.Fatalf("expected proxy de.example:443, got %q", candidate.Addr)
	}
	if candidate.CountryName != "Germany" || candidate.CountryCode != "DE" {
		t.Fatalf("unexpected country metadata: %#v", candidate)
	}
	if candidate.CityName != "Frankfurt" || candidate.CityCode != "fra" {
		t.Fatalf("unexpected city metadata: %#v", candidate)
	}
}

func TestResolveProxyMatchesExplicitProxyMetadata(t *testing.T) {
	t.Parallel()

	countries := []serverlist.Country{
		{
			Name: "Japan",
			Code: "JP",
			Cities: []serverlist.City{
				{
					Name: "Tokyo",
					Code: "tyo",
					Servers: []serverlist.Server{
						{Hostname: "jp.example", Port: 443},
					},
				},
			},
		},
	}

	got, err := resolveProxy("https://jp.example", countries)
	if err != nil {
		t.Fatalf("resolveProxy returned error: %v", err)
	}
	if got.Addr != "https://jp.example" {
		t.Fatalf("expected original proxy flag to be preserved, got %q", got.Addr)
	}
	if got.CountryCode != "JP" || got.CityCode != "tyo" {
		t.Fatalf("expected explicit proxy metadata match, got %#v", got)
	}
}

func TestSelectProxyCandidateRequiresExplicitCountry(t *testing.T) {
	t.Parallel()

	countries := []serverlist.Country{
		{
			Name: "United States",
			Code: "US",
			Cities: []serverlist.City{{
				Name:    "United States",
				Code:    "US",
				Servers: []serverlist.Server{{Hostname: "us.example", Port: 443}},
			}},
		},
		{
			Name: "France",
			Code: "FR",
			Cities: []serverlist.City{{
				Name:    "France",
				Code:    "LFPB",
				Servers: []serverlist.Server{{Hostname: "fr.example", Port: 443}},
			}},
		},
	}

	_, err := selectProxyCandidate(countries, "", nil)
	if err == nil || !strings.Contains(err.Error(), "multiple VPN countries") {
		t.Fatalf("expected explicit-country error, got %v", err)
	}
}

func TestSelectProxyCandidateFiltersCountry(t *testing.T) {
	t.Parallel()

	countries := []serverlist.Country{
		{
			Name: "United States",
			Code: "US",
			Cities: []serverlist.City{{
				Name: "United States",
				Code: "US",
				Servers: []serverlist.Server{
					{Hostname: "us-primary.example", Port: 443},
					{Hostname: "us-secondary.example", Port: 443},
				},
			}},
		},
		{
			Name: "France",
			Code: "FR",
			Cities: []serverlist.City{{
				Name:    "France",
				Code:    "LFPB",
				Servers: []serverlist.Server{{Hostname: "fr.example", Port: 443}},
			}},
		},
	}

	for _, filter := range []string{"US", "united states"} {
		got, err := selectProxyCandidate(countries, filter, nil)
		if err != nil {
			t.Fatalf("selectProxyCandidate(%q) returned error: %v", filter, err)
		}
		// One of the US servers, at random as in Firefox; never France's.
		if got.Addr != "us-primary.example:443" && got.Addr != "us-secondary.example:443" {
			t.Fatalf("expected a US proxy for %q, got %q", filter, got.Addr)
		}
	}
}

func TestResolveProxyReusesPersistedSelection(t *testing.T) {
	t.Parallel()

	path := filepath.Join(t.TempDir(), "proxy-selection.json")
	want := Candidate{
		Addr:        "stable.example:443",
		CountryName: "United States",
		CountryCode: "US",
		CityName:    "San Jose",
		CityCode:    "SJC",
	}
	if err := SaveSelection(path, want); err != nil {
		t.Fatalf("saveProxySelection returned error: %v", err)
	}

	got, fromState, err := resolveProxyWithState("", nil, path)
	if err != nil {
		t.Fatalf("resolveProxyWithState returned error: %v", err)
	}
	if !fromState {
		t.Fatal("expected persisted proxy selection to be reused")
	}
	if got != want {
		t.Fatalf("expected %#v, got %#v", want, got)
	}
}

func TestResolveProxyReplacesSelectionMissingFromFreshServerList(t *testing.T) {
	t.Parallel()

	path := filepath.Join(t.TempDir(), "proxy-selection.json")
	if err := SaveSelection(path, Candidate{Addr: "stale.example:443"}); err != nil {
		t.Fatalf("saveProxySelection returned error: %v", err)
	}
	countries := []serverlist.Country{{
		Name: "Japan",
		Code: "JP",
		Cities: []serverlist.City{{
			Name: "Tokyo",
			Code: "TYO",
			Servers: []serverlist.Server{{
				Hostname: "current.example",
				Port:     443,
			}},
		}},
	}}

	got, fromState, err := resolveProxyWithState("", countries, path)
	if err != nil {
		t.Fatalf("resolveProxyWithState returned error: %v", err)
	}
	if fromState {
		t.Fatal("expected stale persisted selection to be replaced")
	}
	if got.Addr != "current.example:443" {
		t.Fatalf("expected current server-list proxy, got %q", got.Addr)
	}
}

func TestResolveProxyReplacesPersistedSelectionForConfiguredCountry(t *testing.T) {
	t.Parallel()

	path := filepath.Join(t.TempDir(), "proxy-selection.json")
	if err := SaveSelection(path, Candidate{
		Addr:        "us.example:443",
		CountryName: "United States",
		CountryCode: "US",
	}); err != nil {
		t.Fatalf("saveProxySelection returned error: %v", err)
	}
	countries := []serverlist.Country{{
		Name: "France",
		Code: "FR",
		Cities: []serverlist.City{{
			Name:    "France",
			Code:    "LFPB",
			Servers: []serverlist.Server{{Hostname: "fr.example", Port: 443}},
		}},
	}}

	got, fromState, err := ResolveWithStateAndCountry("", "FR", countries, path, nil)
	if err != nil {
		t.Fatalf("resolveProxyWithStateAndCountry returned error: %v", err)
	}
	if fromState {
		t.Fatal("expected configured country to replace mismatched persisted selection")
	}
	if got.Addr != "fr.example:443" || got.CountryCode != "FR" {
		t.Fatalf("expected French proxy, got %#v", got)
	}
}

func TestSelectProxyCandidateDefaultsToRecommendedLocation(t *testing.T) {
	got, err := selectProxyCandidate(liveShapedCountries(), "", nil)
	if err != nil {
		t.Fatal(err)
	}
	if got.Addr != "anycast.example:2499" || !got.IsRecommended() {
		t.Fatalf("expected the recommended location, got %#v", got)
	}
}

func TestSelectProxyCandidateChoosesLockedCountry(t *testing.T) {
	// GB is marked locked in the server list; it is chosen like any other.
	got, err := selectProxyCandidate(liveShapedCountries(), "GB", nil)
	if err != nil || got.Addr != "gb.example:2499" || got.CountryCode != "GB" {
		t.Fatalf("expected the GB proxy, got %#v %v", got, err)
	}
}

func TestSelectProxyCandidateUnknownCountryListsLockedCodes(t *testing.T) {
	_, err := selectProxyCandidate(liveShapedCountries(), "ZZ", nil)
	if err == nil || !strings.Contains(err.Error(), "US,GB,") {
		t.Fatalf("expected an error listing every country code, got %v", err)
	}
}

func TestSelectProxyCandidateCountryFilterSkipsRecommendedRecord(t *testing.T) {
	got, err := selectProxyCandidate(liveShapedCountries(), "US", nil)
	if err != nil || got.Addr != "us.example:2499" {
		t.Fatalf("expected the US proxy, got %#v %v", got, err)
	}
}

func TestResolveProxyKeepsPersistedLockedSelection(t *testing.T) {
	path := t.TempDir() + "/proxy-selection.json"
	if err := SaveSelection(path, Candidate{Addr: "gb.example:2499", CountryCode: "GB"}); err != nil {
		t.Fatal(err)
	}
	got, fromState, err := ResolveWithStateAndCountry("", "GB", liveShapedCountries(), path, nil)
	if err != nil || !fromState || got.Addr != "gb.example:2499" || got.CountryName != "United Kingdom" {
		t.Fatalf("expected the persisted locked selection to be reused, got %#v fromState=%v err=%v", got, fromState, err)
	}
}

func TestConnectProxyCandidatesDefaultMissingPortTo443(t *testing.T) {
	countries := []serverlist.Country{{
		Name: "Japan", Code: "JP",
		Cities: []serverlist.City{{Name: "Tokyo", Code: "TYO", Servers: []serverlist.Server{
			{Hostname: "jp.example"},
			{Hostname: "jp2.example", Port: 2499, Protocols: []serverlist.Protocol{
				{Name: "masque", Host: "masque.example", Port: 443},
				{Name: "connect"},
			}},
		}}},
	}}
	got := connectProxyHosts(countries)
	if len(got) != 2 || got[0] != "jp.example:443" || got[1] != "jp2.example:2499" {
		t.Fatalf("unexpected CONNECT candidates: %v", got)
	}
}
