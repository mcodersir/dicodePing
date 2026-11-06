package routing

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"net/netip"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// pb encodes protobuf fields for test lists.
type pb []byte

func (b pb) varint(v uint64) pb {
	for v >= 0x80 {
		b = append(b, byte(v)|0x80)
		v >>= 7
	}
	return append(b, byte(v))
}

func (b pb) bytes(field int, data []byte) pb {
	b = b.varint(uint64(field)<<3 | 2).varint(uint64(len(data)))
	return append(b, data...)
}

func (b pb) number(field int, v uint64) pb { return b.varint(uint64(field) << 3).varint(v) }

type testDomain struct {
	kind  int
	value string
}

func geoSiteFile(tags map[string][]testDomain) []byte {
	var list pb
	for tag, domains := range tags {
		entry := pb{}.bytes(1, []byte(strings.ToUpper(tag)))
		for _, d := range domains {
			entry = entry.bytes(2, pb{}.number(1, uint64(d.kind)).bytes(2, []byte(d.value)))
		}
		list = list.bytes(1, entry)
	}
	return list
}

func geoIPFile(tags map[string][]string) []byte {
	var list pb
	for tag, cidrs := range tags {
		entry := pb{}.bytes(1, []byte(tag))
		for _, c := range cidrs {
			p := netip.MustParsePrefix(c)
			entry = entry.bytes(2, pb{}.bytes(1, p.Addr().AsSlice()).number(2, uint64(p.Bits())))
		}
		list = list.bytes(1, entry)
	}
	return list
}

func writeLists(t *testing.T) string {
	t.Helper()
	dir := t.TempDir()
	site := geoSiteFile(map[string][]testDomain{
		"all": {{domainSuffix, "ir"}, {domainSuffix, "digikala.com"}, {domainFull, "only.example"}, {domainPlain, "shatel"}, {domainRegex, `^cdn\d+\.example\.net$`}},
		"ads": {{domainSuffix, "ads.example"}},
	})
	ip := geoIPFile(map[string][]string{
		"ir":      {"5.160.0.0/14", "2.144.0.0/14", "2a01:5ec0::/29"},
		"private": {"10.0.0.0/8", "192.168.0.0/16", "fc00::/7"},
	})
	if err := os.WriteFile(filepath.Join(dir, GeoSiteFile), site, 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, GeoIPFile), ip, 0o600); err != nil {
		t.Fatal(err)
	}
	return dir
}

func TestRouterDecides(t *testing.T) {
	dir := writeLists(t)
	r, err := New(Config{
		Dir:    dir,
		Direct: []string{"geosite:all", "geoip:ir", "geoip:private", "domain:my.example", "203.0.113.7"},
		Block:  []string{"geosite:ads", "full:bad.ir"},
	})
	if err != nil {
		t.Fatal(err)
	}
	ctx := context.Background()
	for host, want := range map[string]Action{
		"divar.ir":             Direct, // suffix ir
		"www.digikala.com":     Direct,
		"digikala.com.":        Direct,
		"notdigikala.com":      Proxy, // suffixes stop at a label
		"only.example":         Direct,
		"sub.only.example":     Proxy, // full name only
		"www.shatel.example":   Direct,
		"cdn12.example.net":    Direct,
		"cdnx.example.net":     Proxy,
		"google.com":           Proxy,
		"x.ads.example":        Block,
		"bad.ir":               Block, // block wins over direct
		"api.my.example":       Direct,
		"5.161.2.3":            Direct,
		"8.8.8.8":              Proxy,
		"192.168.1.10":         Direct,
		"203.0.113.7":          Direct,
		"203.0.113.8":          Proxy,
		"[2a01:5ec0:1::1]":     Direct,
		"2001:4860:4860::8888": Proxy,
	} {
		if got := r.Decide(ctx, host, nil); got != want {
			t.Errorf("%s: %s, want %s", host, got, want)
		}
	}
	if !strings.Contains(r.Summary, "geosite:all=5") || !strings.Contains(r.Summary, "geoip:ir=") {
		t.Fatalf("summary %q", r.Summary)
	}
}

// Names are looked up for IP rules only when asked to.
func TestRouterResolvesNamesWhenAsked(t *testing.T) {
	dir := writeLists(t)
	looked := 0
	lookup := func(ctx context.Context, host string) ([]netip.Addr, error) {
		looked++
		if host == "iranian-host.example" {
			return []netip.Addr{netip.MustParseAddr("5.160.10.10")}, nil
		}
		return nil, errors.New("no such host")
	}

	off, err := New(Config{Dir: dir, Direct: []string{"geoip:ir"}})
	if err != nil {
		t.Fatal(err)
	}
	if off.Decide(context.Background(), "iranian-host.example", lookup) != Proxy || looked != 0 {
		t.Fatal("without ResolveDomains a name is not looked up")
	}
	on, err := New(Config{Dir: dir, Direct: []string{"geoip:ir"}, ResolveDomains: true})
	if err != nil {
		t.Fatal(err)
	}
	if on.Decide(context.Background(), "iranian-host.example", lookup) != Direct {
		t.Fatal("the name resolves to an Iranian address")
	}
	if on.Decide(context.Background(), "unknown.example", lookup) != Proxy {
		t.Fatal("a failed lookup goes through the proxy")
	}
	if on.Decide(context.Background(), "iranian-host.example", nil) != Proxy {
		t.Fatal("without a lookup a name goes through the proxy")
	}
}

func TestRouterRejectsBadRulesAndTags(t *testing.T) {
	dir := writeLists(t)
	for _, rules := range [][]string{{"geosite:missing"}, {"geoip:zz"}, {"regexp:("}, {"what is this"}} {
		if _, err := New(Config{Dir: dir, Direct: rules}); err == nil {
			t.Errorf("%v: expected an error", rules)
		}
	}
	if _, err := New(Config{Dir: t.TempDir(), Direct: []string{"geosite:all"}}); err == nil {
		t.Error("a missing file is an error")
	}
	if err := Validate([]string{"geosite:all", "domain:x.example", "10.0.0.0/8", "example.org"}); err != nil {
		t.Errorf("valid rules: %v", err)
	}
	if err := Validate([]string{"geosite:"}); err == nil {
		t.Error("a rule without a tag is invalid")
	}
}

// A download replaces a list only with a complete, readable list.
func TestDownloadKeepsOldListOnFailure(t *testing.T) {
	good := geoSiteFile(map[string][]testDomain{"all": {{domainSuffix, "ir"}}})
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/site.dat", "/ip.dat":
			_, _ = w.Write(good)
		case "/broken.dat":
			_, _ = w.Write([]byte("<html>not a list</html>"))
		default:
			http.NotFound(w, r)
		}
	}))
	defer server.Close()
	dir := filepath.Join(t.TempDir(), "routing")

	if !Due(dir, time.Hour, nil) {
		t.Fatal("missing lists are due")
	}
	if err := Download(context.Background(), server.Client(), dir, server.URL+"/site.dat", server.URL+"/ip.dat", nil); err != nil {
		t.Fatal(err)
	}
	if Due(dir, time.Hour, nil) || len(Files(dir, nil)) != 2 {
		t.Fatalf("fresh lists are not due: %+v", Files(dir, nil))
	}
	// The folder records where the lists came from: other URLs download
	// them again although they are fresh.
	if SourceChanged(dir, server.URL+"/site.dat", server.URL+"/ip.dat") {
		t.Fatal("the same URLs are no change")
	}
	if !SourceChanged(dir, DefaultGeoSiteURL, DefaultGeoIPURL) {
		t.Fatal("other URLs are a change")
	}
	err := Download(context.Background(), server.Client(), dir, server.URL+"/broken.dat", server.URL+"/gone.dat", nil)
	if err == nil || !strings.Contains(err.Error(), "not a v2ray geo list") || !strings.Contains(err.Error(), "HTTP 404") {
		t.Fatalf("expected both failures, got %v", err)
	}
	if data, _ := os.ReadFile(filepath.Join(dir, GeoSiteFile)); string(data) != string(good) {
		t.Fatal("a failed download must keep the old list")
	}
	if !SourceChanged(dir, server.URL+"/site.dat", server.URL+"/ip.dat") {
		t.Fatal("after a failed download the lists are tried again")
	}
	// A folder from before the record holds the default lists.
	if SourceChanged(t.TempDir(), DefaultGeoSiteURL, DefaultGeoIPURL) {
		t.Fatal("an old folder with the defaults is no change")
	}
}

// Each region has its usual list set: Loyalsoldier's for China,
// Chocolate4U's for the others (Iran's rules need its geosite:ir).
func TestRegionSources(t *testing.T) {
	for region, want := range map[string]string{RegionIran: "chocolate4u", RegionChina: "loyalsoldier", RegionRussia: "chocolate4u", RegionTurkey: "chocolate4u", NoRegion: "chocolate4u"} {
		if got := RegionSource(region).ID; got != want {
			t.Errorf("%q: %s, want %s", region, got, want)
		}
	}
	for _, src := range Sources {
		if found, ok := SourceOf(src.GeoSiteURL, src.GeoIPURL); !ok || found.ID != src.ID {
			t.Errorf("SourceOf(%s) = %v %v", src.ID, found, ok)
		}
	}
	if _, ok := SourceOf("https://example.com/site.dat", DefaultGeoIPURL); ok {
		t.Error("lists set by hand are no offered source")
	}
}

// Every region's presets come first, keep private networks direct, and
// name tags the default lists carry; the user's rules follow without
// repeats.
func TestRegionRules(t *testing.T) {
	want := map[string][]string{
		"ir": {"geosite:ir", "ext:iran.dat:ir", "geoip:ir", "geoip:private"},
		"cn": {"geosite:cn", "geoip:cn", "geoip:private"},
		"ru": {"geosite:category-ru", "geosite:tld-ru", "geoip:ru", "geoip:private"},
		"af": {"domain:af", "geoip:af", "geoip:private"},
		"tr": {"domain:tr", "geoip:tr", "geoip:private"},
		"id": {"domain:id", "geoip:id", "geoip:private"},
		"br": {"domain:br", "geoip:br", "geoip:private"},
		"":   {"geoip:private"},
	}
	if len(Regions) != len(want) {
		t.Fatalf("regions %v", Regions)
	}
	for _, region := range Regions {
		got := RegionRules(region)
		if strings.Join(got, " ") != strings.Join(want[region], " ") {
			t.Errorf("%q: %v, want %v", region, got, want[region])
		}
		if err := ValidateRegion(region); err != nil {
			t.Errorf("%q: %v", region, err)
		}
		if err := Validate(got); err != nil {
			t.Errorf("%q presets: %v", region, err)
		}
	}
	if err := ValidateRegion("de"); err == nil {
		t.Error("an unknown region is an error")
	}
	got := WithRegionRules("ir", []string{"domain:my.example", "geoip:private", " geoip:IR "})
	if strings.Join(got, " ") != "geosite:ir ext:iran.dat:ir geoip:ir geoip:private domain:my.example" {
		t.Errorf("direct rules %v", got)
	}
	// The presets are copies: changing the result leaves them alone.
	got[0] = "changed"
	if RegionRules("ir")[0] != "geosite:ir" {
		t.Error("the presets changed")
	}

	// Another region swaps the presets; the user's own rules stay, and a
	// preset the user removed does not come back from the old region.
	edited := []string{"geosite:ir", "geoip:ir", "geoip:private", "domain:my.example"}
	swapped := SwapRegionRules("ir", "tr", edited)
	if strings.Join(swapped, " ") != "domain:tr geoip:tr geoip:private domain:my.example" {
		t.Errorf("swapped %v", swapped)
	}

	// Only the files the rules name are downloaded.
	if files := FilesFor([]string{"geosite:ir", "EXT:iran.dat:ir"}); len(files) != 1 || files[0].Name != IranFile {
		t.Errorf("files %v", files)
	}
	if files := FilesFor([]string{"geosite:cn"}); len(files) != 0 {
		t.Errorf("files without ext: %v", files)
	}
}

// A region's presets route its sites and networks directly.
func TestRegionRoutesDirectly(t *testing.T) {
	dir := t.TempDir()
	site := geoSiteFile(map[string][]testDomain{"ir": {{domainSuffix, "ir"}, {domainSuffix, "digikala.com"}}})
	ip := geoIPFile(map[string][]string{
		"ir":      {"5.160.0.0/14"},
		"tr":      {"78.160.0.0/11"},
		"private": {"10.0.0.0/8", "192.168.0.0/16"},
	})
	if err := os.WriteFile(filepath.Join(dir, GeoSiteFile), site, 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, GeoIPFile), ip, 0o600); err != nil {
		t.Fatal(err)
	}
	for region, cases := range map[string]map[string]Action{
		"ir": {"www.digikala.com": Direct, "5.161.0.1": Direct, "192.168.1.1": Direct, "shop.com.tr": Proxy, "78.160.0.1": Proxy},
		"tr": {"shop.com.tr": Direct, "78.160.0.1": Direct, "192.168.1.1": Direct, "www.digikala.com": Proxy},
		"":   {"192.168.1.1": Direct, "www.digikala.com": Proxy, "5.161.0.1": Proxy},
	} {
		r, err := New(Config{Dir: dir, Direct: RegionRules(region)})
		if err != nil {
			t.Fatalf("%q: %v", region, err)
		}
		for host, want := range cases {
			if got := r.Decide(context.Background(), host, nil); got != want {
				t.Errorf("%q %s: %s, want %s", region, host, got, want)
			}
		}
	}
}

// ext:FILE:TAG reads a tag of another geosite file; a file not downloaded
// yet leaves its rules out without breaking the routing.
func TestExtRulesReadAnotherGeoSiteFile(t *testing.T) {
	dir := t.TempDir()
	cfg := Config{Dir: dir, Direct: []string{"ext:iran.dat:ir", "domain:local.test"}}

	r, err := New(cfg)
	if err != nil {
		t.Fatalf("a missing extra file must not fail the routing: %v", err)
	}
	if len(r.Missing) != 1 || r.Missing[0] != IranFile {
		t.Fatalf("missing %v", r.Missing)
	}
	if r.Decide(context.Background(), "www.local.test", nil) != Direct {
		t.Fatal("the other rules still apply")
	}

	site := geoSiteFile(map[string][]testDomain{"IR": {{domainSuffix, "bank.test"}}})
	if err := os.WriteFile(filepath.Join(dir, IranFile), site, 0o600); err != nil {
		t.Fatal(err)
	}
	r, err = New(cfg)
	if err != nil {
		t.Fatal(err)
	}
	if len(r.Missing) != 0 || r.Decide(context.Background(), "app.bank.test", nil) != Direct {
		t.Fatalf("ext rule not applied: missing %v", r.Missing)
	}
	if _, err := New(Config{Dir: dir, Direct: []string{"ext:iran.dat:nope"}}); err == nil {
		t.Fatal("a tag the file lacks is an error")
	}
	for _, bad := range []string{"ext:iran.dat", "ext:../x.dat:ir", "ext:list.txt:ir"} {
		if err := Validate([]string{bad}); err == nil {
			t.Errorf("%q must be refused", bad)
		}
	}
}

func TestIranAddsTheHostedDomainsFile(t *testing.T) {
	rules := strings.Join(RegionRules(RegionIran), " ")
	if !strings.Contains(rules, "ext:iran.dat:ir") {
		t.Fatalf("Iran's rules: %s", rules)
	}
	if f := FilesFor(RegionRules(RegionIran)); len(f) != 1 || f[0].Name != IranFile || !strings.HasPrefix(f[0].URL, "https://github.com/bootmortis/") {
		t.Fatalf("Iran's files: %+v", f)
	}
	if FilesFor(RegionRules(RegionChina)) != nil {
		t.Fatal("China has no extra file")
	}
}
