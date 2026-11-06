package routing

import (
	"bytes"
	"fmt"
	"net/netip"
	"regexp"
	"sort"
	"strings"
)

// DomainSet matches host names. Full and suffix names are map lookups (one
// per label of the name), so the size of the list does not slow matching;
// keywords and regular expressions, rare in practice, are checked in turn.
type DomainSet struct {
	full     map[string]struct{}
	suffix   map[string]struct{}
	keywords []string
	regexps  []*regexp.Regexp
}

func newDomainSet() *DomainSet {
	return &DomainSet{full: make(map[string]struct{}), suffix: make(map[string]struct{})}
}

func (s *DomainSet) add(kind int, value string) error {
	value = strings.ToLower(strings.TrimSuffix(strings.TrimSpace(value), "."))
	if value == "" {
		return nil
	}
	switch kind {
	case domainFull:
		s.full[value] = struct{}{}
	case domainSuffix:
		s.suffix[value] = struct{}{}
	case domainPlain:
		s.keywords = append(s.keywords, value)
	case domainRegex:
		re, err := regexp.Compile(value)
		if err != nil {
			return fmt.Errorf("regexp %q: %w", value, err)
		}
		s.regexps = append(s.regexps, re)
	default:
		return fmt.Errorf("unknown domain type %d", kind)
	}
	return nil
}

// Len is the number of entries.
func (s *DomainSet) Len() int {
	return len(s.full) + len(s.suffix) + len(s.keywords) + len(s.regexps)
}

// Contains reports whether host (lower case, without a trailing dot)
// matches.
func (s *DomainSet) Contains(host string) bool {
	if _, ok := s.full[host]; ok {
		return true
	}
	for name := host; ; {
		if _, ok := s.suffix[name]; ok {
			return true
		}
		dot := strings.IndexByte(name, '.')
		if dot < 0 {
			break
		}
		name = name[dot+1:]
	}
	for _, k := range s.keywords {
		if strings.Contains(host, k) {
			return true
		}
	}
	for _, re := range s.regexps {
		if re.MatchString(host) {
			return true
		}
	}
	return false
}

// IPSet matches addresses against sorted, merged ranges with a binary
// search.
type IPSet struct {
	prefixes []netip.Prefix
	v4       []ipRange
	v6       []ipRange
}

type ipRange struct{ lo, hi [16]byte }

func (s *IPSet) add(p netip.Prefix) { s.prefixes = append(s.prefixes, p) }

// Len is the number of merged ranges.
func (s *IPSet) Len() int { return len(s.v4) + len(s.v6) }

// finish turns the added prefixes into merged, sorted ranges.
func (s *IPSet) finish() {
	var v4, v6 []ipRange
	for _, p := range s.prefixes {
		r := prefixRange(p)
		if p.Addr().Is4() {
			v4 = append(v4, r)
		} else {
			v6 = append(v6, r)
		}
	}
	s.v4, s.v6, s.prefixes = mergeRanges(v4), mergeRanges(v6), nil
}

func prefixRange(p netip.Prefix) ipRange {
	p = p.Masked()
	lo := p.Addr().As16()
	hi := lo
	bits := p.Bits()
	if p.Addr().Is4() {
		bits += 96
	}
	for i := bits; i < 128; i++ {
		hi[i/8] |= 1 << (7 - uint(i%8))
	}
	return ipRange{lo, hi}
}

func mergeRanges(rs []ipRange) []ipRange {
	sort.Slice(rs, func(i, j int) bool { return bytes.Compare(rs[i].lo[:], rs[j].lo[:]) < 0 })
	var out []ipRange
	for _, r := range rs {
		if n := len(out); n > 0 {
			if after := next(out[n-1].hi); bytes.Compare(r.lo[:], after[:]) <= 0 {
				if bytes.Compare(r.hi[:], out[n-1].hi[:]) > 0 {
					out[n-1].hi = r.hi
				}
				continue
			}
		}
		out = append(out, r)
	}
	return out
}

// next returns a+1, or a when a is the last address.
func next(a [16]byte) [16]byte {
	for i := 15; i >= 0; i-- {
		a[i]++
		if a[i] != 0 {
			return a
		}
	}
	return [16]byte{0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff}
}

// Contains reports whether addr is in the set.
func (s *IPSet) Contains(addr netip.Addr) bool {
	addr = addr.Unmap()
	rs := s.v6
	if addr.Is4() {
		rs = s.v4
	}
	a := addr.As16()
	i := sort.Search(len(rs), func(i int) bool { return bytes.Compare(rs[i].hi[:], a[:]) >= 0 })
	return i < len(rs) && bytes.Compare(rs[i].lo[:], a[:]) <= 0
}
