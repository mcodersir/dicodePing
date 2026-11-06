package proxy

import "testing"

// Like Firefox's server list: the first city that matches, one of its
// servers at random, never a server of another city.
func TestPickInFirstCityPicksAServerOfTheFirstCity(t *testing.T) {
	t.Parallel()

	candidates := []Candidate{
		{Addr: "fr1:443", CountryCode: "FR", CityCode: "par"},
		{Addr: "de1:443", CountryCode: "DE", CityCode: "ber"},
		{Addr: "de2:443", CountryCode: "DE", CityCode: "ber"},
		{Addr: "de3:443", CountryCode: "DE", CityCode: "fra"},
		{Addr: "de4:443", CountryCode: "DE", CityCode: "ber"},
	}
	german := func(c Candidate) bool { return c.CountryCode == "DE" }
	seen := map[string]bool{}
	for i := 0; i < 200; i++ {
		pick, ok := pickInFirstCity(candidates, german)
		if !ok {
			t.Fatal("expected a German server")
		}
		seen[pick.Addr] = true
	}
	if seen["fr1:443"] || seen["de3:443"] {
		t.Fatalf("picked outside Berlin: %v", seen)
	}
	if !seen["de1:443"] || !seen["de2:443"] || !seen["de4:443"] {
		t.Fatalf("expected every Berlin server in 200 picks: %v", seen)
	}
	if _, ok := pickInFirstCity(candidates, func(c Candidate) bool { return c.CountryCode == "US" }); ok {
		t.Fatal("no match must report false")
	}
}
