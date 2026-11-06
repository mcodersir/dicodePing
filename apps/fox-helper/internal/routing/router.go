// Package routing decides, per destination, whether a connection goes
// through Mozilla's proxy, directly through the local network, or nowhere.
// Rules name v2ray geo lists (geosite:TAG, geoip:TAG) or single domains and
// networks; the lists are read once into memory, so a decision takes
// microseconds.
package routing

import (
	"context"
	"errors"
	"fmt"
	"net/netip"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"
)

// Action is where a connection goes.
type Action int

const (
	Proxy  Action = iota // through Mozilla's proxy (no rule matched)
	Direct               // through the local network
	Block                // refused
)

func (a Action) String() string {
	switch a {
	case Direct:
		return "direct"
	case Block:
		return "block"
	}
	return "proxy"
}

// File names in the routing folder.
const (
	GeoSiteFile = "geosite.dat"
	GeoIPFile   = "geoip.dat"
)

// rule kinds
const (
	ruleGeoSite = "geosite"
	ruleGeoIP   = "geoip"
	ruleDomain  = "domain"
	ruleFull    = "full"
	ruleKeyword = "keyword"
	ruleRegexp  = "regexp"
	ruleIP      = "ip"
	// ruleExt is v2ray's ext:FILE:TAG, a tag of another geosite file in
	// the routing folder; its value is "FILE:TAG".
	ruleExt = "ext"
)

type rule struct{ kind, value string }

// parseRule reads one rule: geosite:TAG, geoip:TAG, ext:FILE:TAG (a tag of
// another geosite file), domain:NAME (the name and names under it),
// full:NAME, keyword:TEXT, regexp:EXPR, an IP address or CIDR, or a bare
// name (as domain:).
func parseRule(text string) (rule, error) {
	text = strings.TrimSpace(text)
	if text == "" {
		return rule{}, errors.New("empty rule")
	}
	if kind, value, ok := strings.Cut(text, ":"); ok {
		kind = strings.ToLower(kind)
		switch kind {
		case ruleGeoSite, ruleGeoIP:
			if value == "" {
				return rule{}, fmt.Errorf("%q: a tag is needed", text)
			}
			return rule{kind, strings.ToLower(value)}, nil
		case ruleExt:
			file, tag, ok := strings.Cut(value, ":")
			if !ok || tag == "" || file == "" || filepath.Base(file) != file || !strings.HasSuffix(strings.ToLower(file), ".dat") {
				return rule{}, fmt.Errorf("%q: ext:FILE.dat:TAG is needed, the file in the routing folder", text)
			}
			return rule{kind, file + ":" + strings.ToLower(tag)}, nil
		case ruleDomain, ruleFull, ruleKeyword, ruleRegexp:
			if value == "" {
				return rule{}, fmt.Errorf("%q: a value is needed", text)
			}
			if kind != ruleRegexp {
				value = strings.ToLower(strings.TrimSuffix(value, "."))
			}
			return rule{kind, value}, nil
		}
	}
	if p, err := netip.ParsePrefix(text); err == nil {
		return rule{ruleIP, p.Masked().String()}, nil
	}
	if a, err := netip.ParseAddr(text); err == nil {
		return rule{ruleIP, netip.PrefixFrom(a, a.BitLen()).String()}, nil
	}
	if strings.ContainsAny(text, " /:") {
		return rule{}, fmt.Errorf("%q is not a rule (geosite:TAG, geoip:TAG, domain:NAME, full:NAME, keyword:TEXT, regexp:EXPR, an IP, or a CIDR)", text)
	}
	return rule{ruleDomain, strings.ToLower(strings.TrimSuffix(text, "."))}, nil
}

// Validate reports the first rule that cannot be read.
func Validate(rules []string) error {
	for _, r := range rules {
		if _, err := parseRule(r); err != nil {
			return err
		}
	}
	return nil
}

// Config is what the router is built from.
type Config struct {
	Dir    string   // folder of geosite.dat and geoip.dat
	Direct []string // rules for direct connections
	Block  []string // rules for refused connections; they win over Direct
	// ResolveDomains looks a name up when no domain rule matched, to apply
	// IP rules to it, with the lookup the caller passes (through Mozilla in
	// the proxy, so a filtered network's DNS cannot answer with its block
	// page address).
	ResolveDomains bool
}

// matcher is one rule list; every set keeps the rule it came from, so a
// decision can name it.
type matcher struct {
	names  []string
	sets   []*DomainSet
	ipName []string
	ips    []*IPSet
}

func (m *matcher) matchName(host string) string {
	for i, s := range m.sets {
		if s.Contains(host) {
			return m.names[i]
		}
	}
	return ""
}

func (m *matcher) matchAddr(a netip.Addr) string {
	for i, s := range m.ips {
		if s.Contains(a) {
			return m.ipName[i]
		}
	}
	return ""
}

func (m *matcher) hasIPRules() bool { return len(m.ips) > 0 }

// Router decides where connections go.
type Router struct {
	// Missing names the other geosite files (ext:) that rules name but
	// that are not in the routing folder yet; their rules are left out.
	Missing       []string
	direct, block matcher
	resolve       bool
	// Summary describes what was loaded, for logs and the dashboard.
	Summary string
}

// Decision is a routing decision and why it was taken.
type Decision struct {
	Action Action
	// Rule is the rule that matched, or empty when none did.
	Rule string
	// Resolved is the address a name was looked up to, when IP rules were
	// applied to it.
	Resolved string
}

// LookupFunc resolves a name for ResolveDomains.
type LookupFunc func(ctx context.Context, host string) ([]netip.Addr, error)

// lookupTimeout bounds a name lookup for ResolveDomains.
const lookupTimeout = 3 * time.Second

// New loads the geo lists the rules name and builds a router. A rule
// naming a tag that the file lacks, or a missing file, is an error.
func New(cfg Config) (*Router, error) {
	siteTags, ipTags := map[string]bool{}, map[string]bool{}
	extTags := map[string]map[string]bool{} // file -> tags
	var parsed [2][]rule
	for i, list := range [][]string{cfg.Direct, cfg.Block} {
		for _, text := range list {
			r, err := parseRule(text)
			if err != nil {
				return nil, err
			}
			parsed[i] = append(parsed[i], r)
			switch r.kind {
			case ruleGeoSite:
				siteTags[r.value] = true
			case ruleGeoIP:
				ipTags[r.value] = true
			case ruleExt:
				file, tag, _ := strings.Cut(r.value, ":")
				if extTags[file] == nil {
					extTags[file] = map[string]bool{}
				}
				extTags[file][tag] = true
			}
		}
	}
	var sites map[string]*DomainSet
	var geoips map[string]*IPSet
	var err error
	if len(siteTags) > 0 {
		if sites, err = loadGeoSite(filepath.Join(cfg.Dir, GeoSiteFile), siteTags); err != nil {
			return nil, fmt.Errorf("reading %s: %w", GeoSiteFile, err)
		}
	}
	if len(ipTags) > 0 {
		if geoips, err = loadGeoIP(filepath.Join(cfg.Dir, GeoIPFile), ipTags); err != nil {
			return nil, fmt.Errorf("reading %s: %w", GeoIPFile, err)
		}
	}
	// Other geosite files are optional: one not downloaded yet leaves its
	// rules out (named in Missing) rather than the whole routing.
	exts := map[string]map[string]*DomainSet{}
	var missing []string
	for file, tags := range extTags {
		sets, err := loadGeoSite(filepath.Join(cfg.Dir, file), tags)
		if errors.Is(err, os.ErrNotExist) {
			missing = append(missing, file)
			continue
		}
		if err != nil {
			return nil, fmt.Errorf("reading %s: %w", file, err)
		}
		exts[file] = sets
	}
	sort.Strings(missing)
	r := &Router{resolve: cfg.ResolveDomains, Missing: missing}
	var summary []string
	for i, rules := range parsed {
		var m matcher
		for _, rl := range rules {
			name := rl.kind + ":" + rl.value
			switch rl.kind {
			case ruleGeoSite:
				set := sites[rl.value]
				if set == nil {
					return nil, fmt.Errorf("%s has no tag %q", GeoSiteFile, rl.value)
				}
				m.names, m.sets = append(m.names, name), append(m.sets, set)
				summary = append(summary, fmt.Sprintf("%s=%d", name, set.Len()))
			case ruleExt:
				file, tag, _ := strings.Cut(rl.value, ":")
				sets, loaded := exts[file]
				if !loaded {
					continue
				}
				set := sets[tag]
				if set == nil {
					return nil, fmt.Errorf("%s has no tag %q", file, tag)
				}
				m.names, m.sets = append(m.names, name), append(m.sets, set)
				summary = append(summary, fmt.Sprintf("%s=%d", name, set.Len()))
			case ruleGeoIP:
				set := geoips[rl.value]
				if set == nil {
					return nil, fmt.Errorf("%s has no tag %q", GeoIPFile, rl.value)
				}
				m.ipName, m.ips = append(m.ipName, name), append(m.ips, set)
				summary = append(summary, fmt.Sprintf("%s=%d", name, set.Len()))
			case ruleIP:
				set := &IPSet{}
				set.add(netip.MustParsePrefix(rl.value))
				set.finish()
				m.ipName, m.ips = append(m.ipName, rl.value), append(m.ips, set)
			default:
				set := newDomainSet()
				kinds := map[string]int{ruleDomain: domainSuffix, ruleFull: domainFull, ruleKeyword: domainPlain, ruleRegexp: domainRegex}
				if err := set.add(kinds[rl.kind], rl.value); err != nil {
					return nil, err
				}
				m.names, m.sets = append(m.names, name), append(m.sets, set)
			}
		}
		if i == 0 {
			r.direct = m
		} else {
			r.block = m
		}
	}
	r.Summary = strings.Join(summary, " ")
	return r, nil
}

// Decide returns where a connection to host (a name or an address) goes.
// With ResolveDomains, lookup resolves a name that no domain rule matched;
// a nil lookup, or one that fails, sends the name through the proxy.
func (r *Router) Decide(ctx context.Context, host string, lookup LookupFunc) Action {
	return r.Explain(ctx, host, lookup).Action
}

// Explain decides like Decide and names the rule that matched.
func (r *Router) Explain(ctx context.Context, host string, lookup LookupFunc) Decision {
	host = strings.ToLower(strings.TrimSuffix(strings.Trim(host, "[]"), "."))
	if addr, err := netip.ParseAddr(host); err == nil {
		return r.decideAddr(addr)
	}
	if rule := r.block.matchName(host); rule != "" {
		return Decision{Action: Block, Rule: rule}
	}
	if rule := r.direct.matchName(host); rule != "" {
		return Decision{Action: Direct, Rule: rule}
	}
	if !r.resolve || lookup == nil || (!r.block.hasIPRules() && !r.direct.hasIPRules()) {
		return Decision{Action: Proxy}
	}
	ctx, cancel := context.WithTimeout(ctx, lookupTimeout)
	defer cancel()
	addrs, err := lookup(ctx, host)
	if err != nil || len(addrs) == 0 {
		return Decision{Action: Proxy}
	}
	d := r.decideAddr(addrs[0])
	d.Resolved = addrs[0].String()
	return d
}

func (r *Router) decideAddr(addr netip.Addr) Decision {
	if rule := r.block.matchAddr(addr); rule != "" {
		return Decision{Action: Block, Rule: rule}
	}
	if rule := r.direct.matchAddr(addr); rule != "" {
		return Decision{Action: Direct, Rule: rule}
	}
	return Decision{Action: Proxy}
}
