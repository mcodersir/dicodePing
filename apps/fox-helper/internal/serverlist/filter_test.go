package serverlist

import (
	"encoding/json"
	"testing"
)

func TestCompareVersions(t *testing.T) {
	tests := []struct {
		a, b string
		want int
	}{
		{"160.0a1", "151.0a1", 1},
		{"151.0a1", "151.0a1", 0},
		{"150.0", "151.0a1", -1},
		{"151.0", "151.0a1", 1},
		{"151.0a2", "151.0a1", 1},
		{"151.0b1", "151.0a1", 1},
		{"151.0.1", "151.0", 1},
		{"151", "151.0", 0},
		{"9.0", "10.0", -1},
	}
	for _, tc := range tests {
		if got := CompareVersions(tc.a, tc.b); got != tc.want {
			t.Errorf("CompareVersions(%q, %q) = %d, want %d", tc.a, tc.b, got, tc.want)
		}
	}
}

func TestEvaluateFilterExpression(t *testing.T) {
	filter := Environment{FirefoxVersion: "160.0a1", Country: "DE"}
	tests := []struct {
		expr    string
		want    bool
		wantErr bool
	}{
		{`env.version|versionCompare("151.0a1") >= 0`, true, false},
		{`env.version|versionCompare("151.0a1") < 0`, false, false},
		{`env.version|versionCompare('170.0a1') < 0 && env.country == "DE"`, true, false},
		{`(env.country != "DE")`, false, false},
		{`env.version|versionCompare("151.0a1") >= 0 || env.country == "US"`, false, true},
		{`env.channel == "release"`, false, true},
	}
	for _, tc := range tests {
		got, err := evaluateFilterExpression(tc.expr, filter)
		if (err != nil) != tc.wantErr || got != tc.want {
			t.Errorf("evaluateFilterExpression(%q) = %v, %v; want %v, error=%v", tc.expr, got, err, tc.want, tc.wantErr)
		}
	}
}

func TestFilterSelectsVersionGatedRecord(t *testing.T) {
	// Shape of the live vpn-serverlist collection: two version-gated US
	// records, the recommended record, and a locked country.
	raw := `[
		{"code":"US","name":"United States","filter_expression":"env.version|versionCompare(\"151.0a1\") >= 0","cities":[{"code":"US","name":"United States","servers":[{"hostname":"us.example","port":2499}]}]},
		{"code":"US","name":"USA","filter_expression":"env.version|versionCompare(\"151.0a1\") < 0","cities":[{"code":"US","name":"USA","servers":[{"hostname":"legacy.example","port":2499}]}]},
		{"code":"REC","name":"Recommended","cities":[{"code":"REC","name":"Recommended","servers":[{"hostname":"anycast.example","port":2499}]}]},
		{"code":"GB","name":"United Kingdom","locked":true,"cities":[{"code":"LON","name":"London","servers":[{"hostname":"gb.example","port":2499}]}]},
		{"code":"XX","name":"Unknown","filter_expression":"env.appinfo.OS == \"Linux\"","cities":[{"code":"XX","name":"X","servers":[{"hostname":"x.example"}]}]}
	]`
	var countries []Country
	if err := json.Unmarshal([]byte(raw), &countries); err != nil {
		t.Fatal(err)
	}

	kept, dropped := Filter(countries, Environment{FirefoxVersion: "160.0a1"})
	if len(kept) != 3 || len(dropped) != 2 {
		t.Fatalf("expected 3 kept and 2 dropped records, got %d and %d", len(kept), len(dropped))
	}
	if kept[0].Cities[0].Servers[0].Hostname != "us.example" {
		t.Fatalf("expected the current US record, got %#v", kept[0])
	}
	if !kept[2].Locked {
		t.Fatal("expected the locked flag to be preserved")
	}

	legacy, _ := Filter(countries, Environment{FirefoxVersion: "140.0"})
	if legacy[0].Cities[0].Servers[0].Hostname != "legacy.example" {
		t.Fatalf("expected the legacy US record for an old version, got %#v", legacy[0])
	}
}
