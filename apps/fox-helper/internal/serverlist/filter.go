package serverlist

import (
	"fmt"
	"regexp"
	"strconv"
	"strings"
)

// DefaultFirefoxVersion evaluates Remote Settings filter expressions
// (env.version) when the current version cannot be fetched
// (LatestFirefoxVersion).
const DefaultFirefoxVersion = "160.0a1"

// Environment holds the client properties used to evaluate Remote
// Settings filter expressions.
type Environment struct {
	// FirefoxVersion is matched against env.version.
	FirefoxVersion string
	// Country is matched against env.country; empty when unknown.
	Country string
}

// FilteredRecord describes a server-list record that was dropped because its
// filter expression did not match or could not be evaluated.
type FilteredRecord struct {
	Code       string
	Expression string
	Reason     string
}

// filterServerList keeps the records whose filter expression matches the
// client, as Firefox's Remote Settings client does before the IP Protection
// code sees the list. Expressions that cannot be evaluated fail closed.
func filterServerList(countries []Country, filter Environment) ([]Country, []FilteredRecord) {
	kept := make([]Country, 0, len(countries))
	var dropped []FilteredRecord
	for _, country := range countries {
		expr := strings.TrimSpace(country.FilterExpression)
		if expr == "" {
			kept = append(kept, country)
			continue
		}
		matched, err := evaluateFilterExpression(expr, filter)
		switch {
		case err != nil:
			dropped = append(dropped, FilteredRecord{Code: country.Code, Expression: expr, Reason: err.Error()})
		case !matched:
			dropped = append(dropped, FilteredRecord{Code: country.Code, Expression: expr, Reason: "filter does not match this client"})
		default:
			kept = append(kept, country)
		}
	}
	return kept, dropped
}

var (
	filterVersionTermRe = regexp.MustCompile(`^env\.version\s*\|\s*versionCompare\(\s*(?:"([^"]*)"|'([^']*)')\s*\)\s*(<=|>=|===|!==|==|!=|<|>)\s*(-?\d+)$`)
	filterCountryTermRe = regexp.MustCompile(`^env\.country\s*(===|!==|==|!=)\s*(?:"([^"]*)"|'([^']*)')$`)
)

// evaluateFilterExpression evaluates the JEXL subset used by the
// vpn-serverlist collection: conjunctions (&&) of env.version
// versionCompare terms and env.country equality terms. Anything else is
// reported as unsupported so the caller can fail closed.
func evaluateFilterExpression(expr string, filter Environment) (bool, error) {
	if strings.Contains(expr, "||") {
		return false, fmt.Errorf("unsupported filter expression %q", expr)
	}
	for _, rawTerm := range strings.Split(expr, "&&") {
		term := strings.TrimSpace(rawTerm)
		for strings.HasPrefix(term, "(") && strings.HasSuffix(term, ")") {
			term = strings.TrimSpace(term[1 : len(term)-1])
		}
		if m := filterVersionTermRe.FindStringSubmatch(term); m != nil {
			version := strings.TrimSpace(filter.FirefoxVersion)
			if version == "" {
				version = DefaultFirefoxVersion
			}
			reference := m[1] + m[2]
			want, err := strconv.Atoi(m[4])
			if err != nil {
				return false, fmt.Errorf("unsupported filter expression %q", expr)
			}
			if !compareInts(CompareVersions(version, reference), m[3], want) {
				return false, nil
			}
			continue
		}
		if m := filterCountryTermRe.FindStringSubmatch(term); m != nil {
			equal := strings.EqualFold(strings.TrimSpace(filter.Country), m[2]+m[3])
			if (m[1] == "==" || m[1] == "===") != equal {
				return false, nil
			}
			continue
		}
		return false, fmt.Errorf("unsupported filter expression term %q", term)
	}
	return true, nil
}

func compareInts(got int, op string, want int) bool {
	switch op {
	case "<":
		return got < want
	case "<=":
		return got <= want
	case ">":
		return got > want
	case ">=":
		return got >= want
	case "==", "===":
		return got == want
	case "!=", "!==":
		return got != want
	}
	return false
}

// CompareVersions compares two toolkit version strings with the
// semantics of Mozilla's nsIVersionComparator (used by JEXL versionCompare):
// it returns -1, 0, or 1. Each dot-separated part is <number><string>
// <number><extra>; a missing string sorts after any string, so "160.0" is
// newer than "160.0a1".
func CompareVersions(a, b string) int {
	aParts := strings.Split(a, ".")
	bParts := strings.Split(b, ".")
	for i := 0; i < len(aParts) || i < len(bParts); i++ {
		var ap, bp string
		if i < len(aParts) {
			ap = aParts[i]
		}
		if i < len(bParts) {
			bp = bParts[i]
		}
		if c := compareVersionPart(parseVersionPart(ap), parseVersionPart(bp)); c != 0 {
			return c
		}
	}
	return 0
}

type versionPart struct {
	numA   int64
	strB   string
	hasB   bool
	numC   int64
	extraD string
	hasD   bool
}

func parseVersionPart(part string) versionPart {
	var vp versionPart
	if part == "" {
		return vp
	}
	if part == "*" {
		vp.numA = 1<<31 - 1
		return vp
	}
	numA, rest := leadingInt(part)
	vp.numA = numA
	if strings.HasPrefix(rest, "+") {
		vp.numA++
		vp.strB, vp.hasB = "pre", true
		return vp
	}
	if rest == "" {
		return vp
	}
	idx := strings.IndexAny(rest, "0123456789+-")
	if idx < 0 {
		vp.strB, vp.hasB = rest, true
		return vp
	}
	if idx > 0 {
		vp.strB, vp.hasB = rest[:idx], true
	}
	numC, extra := leadingInt(rest[idx:])
	vp.numC = numC
	if extra != "" {
		vp.extraD, vp.hasD = extra, true
	}
	return vp
}

func leadingInt(s string) (int64, string) {
	end := 0
	if end < len(s) && (s[end] == '-' || s[end] == '+') {
		end++
	}
	digitsStart := end
	for end < len(s) && s[end] >= '0' && s[end] <= '9' {
		end++
	}
	if end == digitsStart {
		return 0, s
	}
	n, err := strconv.ParseInt(s[:end], 10, 64)
	if err != nil {
		return 0, s[end:]
	}
	return n, s[end:]
}

func compareVersionPart(a, b versionPart) int {
	if c := compareInt64(a.numA, b.numA); c != 0 {
		return c
	}
	if c := compareOptionalString(a.strB, a.hasB, b.strB, b.hasB); c != 0 {
		return c
	}
	if c := compareInt64(a.numC, b.numC); c != 0 {
		return c
	}
	return compareOptionalString(a.extraD, a.hasD, b.extraD, b.hasD)
}

func compareInt64(a, b int64) int {
	switch {
	case a < b:
		return -1
	case a > b:
		return 1
	}
	return 0
}

// compareOptionalString orders an absent string after any present one.
func compareOptionalString(a string, hasA bool, b string, hasB bool) int {
	switch {
	case !hasA && !hasB:
		return 0
	case !hasA:
		return 1
	case !hasB:
		return -1
	}
	return strings.Compare(a, b)
}

// Filter drops records whose Remote Settings filter expression does
// not apply to filter; unsupported expressions are dropped (fail closed).
func Filter(countries []Country, filter Environment) ([]Country, []FilteredRecord) {
	return filterServerList(countries, filter)
}
