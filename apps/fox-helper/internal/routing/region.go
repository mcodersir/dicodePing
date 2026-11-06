package routing

import (
	"fmt"
	"strings"
)

// Region codes for routing.region: the country whose sites and networks go
// directly, like the "region" of v2ray clients such as Hiddify. NoRegion
// keeps only private networks direct.
const (
	RegionIran        = "ir"
	RegionChina       = "cn"
	RegionRussia      = "ru"
	RegionAfghanistan = "af"
	RegionTurkey      = "tr"
	RegionIndonesia   = "id"
	RegionBrazil      = "br"
	NoRegion          = ""
)

// privateRule keeps local and private networks off the proxy in every
// region.
const privateRule = "geoip:private"

// regionRules are the preset Direct rules of each region. The default lists
// (Chocolate4U/Iran-v2ray-rules) carry every tag named here; a region
// without a geosite tag in them uses its country-code top-level domain.
var regionRules = map[string][]string{
	RegionIran:        {"geosite:ir", "ext:" + IranFile + ":ir", "geoip:ir"},
	RegionChina:       {"geosite:cn", "geoip:cn"},
	RegionRussia:      {"geosite:category-ru", "geosite:tld-ru", "geoip:ru"},
	RegionAfghanistan: {"domain:af", "geoip:af"},
	RegionTurkey:      {"domain:tr", "geoip:tr"},
	RegionIndonesia:   {"domain:id", "geoip:id"},
	RegionBrazil:      {"domain:br", "geoip:br"},
	NoRegion:          {},
}

// IranFile is bootmortis/iran-hosted-domains' list of sites hosted in
// Iran, more of them than geosite:ir (69,511 names against 57,554 in
// October 2026), in v2ray's geosite format with the tag ir.
const IranFile = "iran.dat"

// IranFileURL is where IranFile comes from: its latest release.
const IranFileURL = "https://github.com/bootmortis/iran-hosted-domains/releases/latest/download/iran.dat"

// ExtraFile is another geosite file that rules name (ext:FILE:TAG).
type ExtraFile struct{ Name, URL string }

// knownFiles are the other geosite files this program can download.
var knownFiles = []ExtraFile{{IranFile, IranFileURL}}

// FilesFor lists the other geosite files that rules name and this program
// can download, to download with the two lists.
func FilesFor(rules []string) []ExtraFile {
	var out []ExtraFile
	for _, f := range knownFiles {
		prefix := "ext:" + strings.ToLower(f.Name) + ":"
		for _, r := range rules {
			if strings.HasPrefix(strings.ToLower(strings.TrimSpace(r)), prefix) {
				out = append(out, f)
				break
			}
		}
	}
	return out
}

// Regions lists the valid region codes, NoRegion last.
var Regions = []string{RegionIran, RegionChina, RegionRussia, RegionAfghanistan, RegionTurkey, RegionIndonesia, RegionBrazil, NoRegion}

// ValidateRegion reports whether region is a known region code.
func ValidateRegion(region string) error {
	if _, ok := regionRules[region]; ok {
		return nil
	}
	return fmt.Errorf("unknown region %q (use one of ir, cn, ru, af, tr, id, br, or \"\" for none)", region)
}

// RegionRules returns the preset Direct rules of region, private networks
// included; an unknown region gets only the private networks.
func RegionRules(region string) []string {
	return append(append([]string{}, regionRules[region]...), privateRule)
}

// WithRegionRules returns region's preset rules followed by direct,
// without repeating a rule the presets have. The presets live in the
// Direct list itself, where the user can change or remove them.
func WithRegionRules(region string, direct []string) []string {
	out := RegionRules(region)
	seen := make(map[string]bool, len(out))
	for _, r := range out {
		seen[r] = true
	}
	for _, r := range direct {
		key := strings.ToLower(strings.TrimSpace(r))
		if seen[key] {
			continue
		}
		seen[key] = true
		out = append(out, r)
	}
	return out
}

// SwapRegionRules replaces from's preset rules in direct with to's (a
// region change): the user's own rules stay, after the new presets.
func SwapRegionRules(from, to string, direct []string) []string {
	old := make(map[string]bool)
	for _, r := range RegionRules(from) {
		old[r] = true
	}
	var rest []string
	for _, r := range direct {
		if !old[strings.ToLower(strings.TrimSpace(r))] {
			rest = append(rest, r)
		}
	}
	return WithRegionRules(to, rest)
}
