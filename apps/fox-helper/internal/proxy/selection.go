package proxy

import (
	"encoding/json"
	"errors"
	"fmt"
	"math/rand/v2"
	"net"
	"net/url"
	"os"
	"path/filepath"
	"slices"
	"strconv"
	"strings"

	"dicodeping/fox/internal/logx"
	"dicodeping/fox/internal/serverlist"
)

type Candidate struct {
	Addr        string
	CountryName string
	CountryCode string
	CityName    string
	CityCode    string
}

// IsRecommended reports whether the candidate belongs to the recommended
// (anycast) location rather than a specific country.
func (p Candidate) IsRecommended() bool {
	return strings.EqualFold(strings.TrimSpace(p.CountryCode), serverlist.RecommendedCountryCode)
}

type proxySelectionState struct {
	Addr        string `json:"addr"`
	CountryName string `json:"country_name,omitempty"`
	CountryCode string `json:"country_code,omitempty"`
	CityName    string `json:"city_name,omitempty"`
	CityCode    string `json:"city_code,omitempty"`
}

func (p Candidate) CountryNameOrUnknown() string {
	if p.CountryName == "" {
		return "unknown"
	}
	return p.CountryName
}

func (p Candidate) CountryCodeOrUnknown() string {
	if p.CountryCode == "" {
		return "unknown"
	}
	return p.CountryCode
}

func (p Candidate) CityNameOrUnknown() string {
	if p.CityName == "" {
		return "unknown"
	}
	return p.CityName
}

func (p Candidate) CityCodeOrUnknown() string {
	if p.CityCode == "" {
		return "unknown"
	}
	return p.CityCode
}

func resolveProxy(proxyFlag string, countries []serverlist.Country) (Candidate, error) {
	candidate, _, err := ResolveWithStateAndCountry(proxyFlag, "", countries, "", nil)
	return candidate, err
}

func resolveProxyWithState(proxyFlag string, countries []serverlist.Country, stateFile string) (Candidate, bool, error) {
	return ResolveWithStateAndCountry(proxyFlag, "", countries, stateFile, nil)
}

// ResolveWithStateAndCountry selects the upstream: proxyFlag when set,
// else the persisted choice in stateFile when it suits countryFilter and is
// still a list entry, else a server of the location (selectProxyCandidate).
// avoided (nil: none) reports servers that failed recently
// (ServerFailover.Avoided): a persisted one is replaced, and selection
// skips them while the location has another.
func ResolveWithStateAndCountry(proxyFlag, countryFilter string, countries []serverlist.Country, stateFile string, avoided func(addr string) bool) (Candidate, bool, error) {
	if proxyFlag != "" {
		if matched, ok := findProxyCandidate(proxyFlag, countries); ok {
			matched.Addr = proxyFlag
			return matched, false, nil
		}
		return Candidate{Addr: proxyFlag}, false, nil
	}

	if stateFile != "" {
		persisted, err := loadProxySelection(stateFile)
		if err == nil {
			if avoided != nil && avoided(persisted.Addr) && len(countries) > 0 {
				logx.Info("persisted proxy failed recently; selecting another server of the location proxy=%s", persisted.Addr)
			} else if proxyCandidateMatchesCountry(persisted, countryFilter) {
				if matched, ok := findProxyCandidate(persisted.Addr, countries); ok {
					matched.Addr = persisted.Addr
					return matched, true, nil
				}
				if len(countries) == 0 {
					return persisted, true, nil
				}
				logx.Warn("persisted proxy is no longer a server-list entry; selecting a replacement proxy=%s", persisted.Addr)
			} else if countryFilter != "" {
				logx.Info("persisted proxy does not match configured country; selecting a replacement proxy=%s persisted_country_code=%s configured_country=%q",
					persisted.Addr,
					persisted.CountryCodeOrUnknown(),
					countryFilter,
				)
			}
		} else if !errors.Is(err, os.ErrNotExist) {
			logx.Warn("loading persisted proxy selection failed path=%s err=%s", stateFile, logx.Err(err))
		}
	}

	candidate, err := selectProxyCandidate(countries, countryFilter, avoided)
	if err != nil {
		return Candidate{}, false, err
	}
	return candidate, false, nil
}

// selectProxyCandidate picks a server of the location countryFilter
// selects (locationMatcher) in its first city, skipping the servers
// avoided reports (nil: none) unless the location has no other.
func selectProxyCandidate(countries []serverlist.Country, countryFilter string, avoided func(addr string) bool) (Candidate, error) {
	proxies := ConnectCandidates(countries)
	if len(proxies) == 0 {
		return Candidate{}, fmt.Errorf("no CONNECT proxies available from server list or persisted state; pass -country CODE or -proxy HOST:PORT")
	}
	match, err := locationMatcher(proxies, countryFilter)
	if err != nil {
		return Candidate{}, err
	}
	if avoided != nil {
		if candidate, ok := pickInFirstCity(proxies, func(c Candidate) bool { return match(c) && !avoided(c.Addr) }); ok {
			return candidate, nil
		}
	}
	if candidate, ok := pickInFirstCity(proxies, match); ok {
		return candidate, nil
	}
	return Candidate{}, fmt.Errorf("no CONNECT proxy found for country %q; available country codes: %s", strings.TrimSpace(countryFilter), availableCountryCodes(proxies))
}

// locationMatcher returns what selects the servers of the location for
// countryFilter: the country's (or the recommended location's for REC and
// "recommended"); without a filter the recommended location's, as in
// Firefox, or every server when the list has a single country and no
// recommended location. Every location is offered, including those the
// server list marks locked: Mozilla's servers accept an ordinary
// account's pass on them.
func locationMatcher(proxies []Candidate, countryFilter string) (func(Candidate) bool, error) {
	countryFilter = strings.TrimSpace(countryFilter)
	if countryFilter != "" {
		return func(c Candidate) bool { return proxyCandidateMatchesCountry(c, countryFilter) }, nil
	}
	if slices.ContainsFunc(proxies, Candidate.IsRecommended) {
		return Candidate.IsRecommended, nil
	}
	selectedCountryCode := ""
	for _, candidate := range proxies {
		code := strings.ToUpper(strings.TrimSpace(candidate.CountryCode))
		if code == "" {
			continue
		}
		if selectedCountryCode == "" {
			selectedCountryCode = code
			continue
		}
		if code != selectedCountryCode {
			return nil, fmt.Errorf("multiple VPN countries are available; pass -country CODE or -proxy HOST:PORT instead of selecting a random country (available: %s)", availableCountryCodes(proxies))
		}
	}
	return func(Candidate) bool { return true }, nil
}

// LocationCandidates lists, in server-list order, the servers of the
// location countryFilter selects (locationMatcher): the servers that
// ServerFailover moves the upstream among. It is empty when the filter
// selects nothing.
func LocationCandidates(countries []serverlist.Country, countryFilter string) []Candidate {
	proxies := ConnectCandidates(countries)
	match, err := locationMatcher(proxies, countryFilter)
	if err != nil {
		return nil
	}
	var location []Candidate
	for _, c := range proxies {
		if match(c) {
			location = append(location, c)
		}
	}
	return location
}

// pickInFirstCity picks, as Firefox's server list does, the first city
// among the candidates that match and one of its servers at random, so
// the users of a location spread over its servers. ok is false when none
// matches.
func pickInFirstCity(candidates []Candidate, match func(Candidate) bool) (pick Candidate, ok bool) {
	var city []Candidate
	for _, c := range candidates {
		if !match(c) {
			continue
		}
		if len(city) > 0 && (c.CountryCode != city[0].CountryCode || c.CityCode != city[0].CityCode || c.CityName != city[0].CityName) {
			continue
		}
		city = append(city, c)
	}
	if len(city) == 0 {
		return Candidate{}, false
	}
	return city[rand.IntN(len(city))], true
}

func proxyCandidateMatchesCountry(candidate Candidate, countryFilter string) bool {
	countryFilter = strings.TrimSpace(countryFilter)
	if countryFilter == "" {
		return true
	}
	if strings.EqualFold(countryFilter, "recommended") {
		return candidate.IsRecommended()
	}
	return strings.EqualFold(strings.TrimSpace(candidate.CountryCode), countryFilter) ||
		strings.EqualFold(strings.TrimSpace(candidate.CountryName), countryFilter)
}

func availableCountryCodes(candidates []Candidate) string {
	seen := make(map[string]struct{})
	codes := make([]string, 0)
	for _, candidate := range candidates {
		code := strings.ToUpper(strings.TrimSpace(candidate.CountryCode))
		if code == "" {
			continue
		}
		if _, ok := seen[code]; ok {
			continue
		}
		seen[code] = struct{}{}
		codes = append(codes, code)
	}
	if len(codes) == 0 {
		return "unknown"
	}
	return strings.Join(codes, ",")
}

func loadProxySelection(path string) (Candidate, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return Candidate{}, err
	}
	var state proxySelectionState
	if err := json.Unmarshal(data, &state); err != nil {
		return Candidate{}, err
	}
	if _, err := canonicalProxyAddr(state.Addr); err != nil {
		return Candidate{}, fmt.Errorf("invalid persisted proxy %q: %w", state.Addr, err)
	}
	return Candidate{
		Addr:        state.Addr,
		CountryName: state.CountryName,
		CountryCode: state.CountryCode,
		CityName:    state.CityName,
		CityCode:    state.CityCode,
	}, nil
}

// PersistedSelection returns the saved choice when it suits countryFilter,
// reading only the file: no server list and no log line. The status shows
// it before the proxy first connects to Mozilla, which selects for real.
func PersistedSelection(path, countryFilter string) (Candidate, bool) {
	candidate, err := loadProxySelection(path)
	if err != nil || !proxyCandidateMatchesCountry(candidate, countryFilter) {
		return Candidate{}, false
	}
	return candidate, true
}

func SaveSelection(path string, candidate Candidate) error {
	if path == "" {
		return nil
	}
	if _, err := canonicalProxyAddr(candidate.Addr); err != nil {
		return err
	}
	return writeProxySelectionState(path, proxySelectionState{
		Addr:        candidate.Addr,
		CountryName: candidate.CountryName,
		CountryCode: candidate.CountryCode,
		CityName:    candidate.CityName,
		CityCode:    candidate.CityCode,
	})
}

func writeProxySelectionState(path string, state proxySelectionState) error {
	data, err := json.MarshalIndent(state, "", "  ")
	if err != nil {
		return err
	}
	data = append(data, '\n')
	dir := filepath.Dir(path)
	if err := os.MkdirAll(dir, 0700); err != nil {
		return err
	}
	tmp, err := os.CreateTemp(dir, "."+filepath.Base(path)+".*.tmp")
	if err != nil {
		return err
	}
	tmpName := tmp.Name()
	defer os.Remove(tmpName)
	if err := tmp.Chmod(0600); err != nil {
		_ = tmp.Close()
		return err
	}
	if _, err := tmp.Write(data); err != nil {
		_ = tmp.Close()
		return err
	}
	if err := tmp.Close(); err != nil {
		return err
	}
	if err := os.Rename(tmpName, path); err != nil {
		if removeErr := os.Remove(path); removeErr != nil && !errors.Is(removeErr, os.ErrNotExist) {
			return err
		}
		if retryErr := os.Rename(tmpName, path); retryErr != nil {
			return retryErr
		}
	}
	return os.Chmod(path, 0600)
}

func findProxyCandidate(proxyFlag string, countries []serverlist.Country) (Candidate, bool) {
	target, err := canonicalProxyAddr(proxyFlag)
	if err != nil {
		return Candidate{}, false
	}
	// One host can serve several records (e.g. the anycast host); the
	// first record in server-list order names it.
	for _, candidate := range ConnectCandidates(countries) {
		candidateAddr, err := canonicalProxyAddr(candidate.Addr)
		if err != nil {
			continue
		}
		if strings.EqualFold(candidateAddr, target) {
			return candidate, true
		}
	}
	return Candidate{}, false
}

func canonicalProxyAddr(raw string) (string, error) {
	proxyURL, err := NormalizeURL(raw)
	if err != nil {
		return "", err
	}
	host := proxyURL.Host
	if proxyURL.Port() == "" {
		host = net.JoinHostPort(proxyURL.Hostname(), "443")
	}
	return strings.ToLower(host), nil
}

func connectProxyHosts(countries []serverlist.Country) []string {
	candidates := ConnectCandidates(countries)
	proxies := make([]string, 0, len(candidates))
	for _, candidate := range candidates {
		proxies = append(proxies, candidate.Addr)
	}
	return proxies
}

func ConnectCandidates(countries []serverlist.Country) []Candidate {
	var proxies []Candidate
	for _, country := range countries {
		for _, city := range country.Cities {
			for _, srv := range city.Servers {
				if srv.Quarantined {
					continue
				}
				// Firefox defaults a missing server port to 443 and a
				// missing protocol list to CONNECT on the server itself.
				serverPort := srv.Port
				if serverPort <= 0 {
					serverPort = serverlist.DefaultServerPort
				}
				candidate := func(host string, port int) Candidate {
					return Candidate{
						Addr:        net.JoinHostPort(host, strconv.Itoa(port)),
						CountryName: country.Name,
						CountryCode: country.Code,
						CityName:    city.Name,
						CityCode:    city.Code,
					}
				}
				if len(srv.Protocols) == 0 {
					if srv.Hostname != "" {
						proxies = append(proxies, candidate(srv.Hostname, serverPort))
					}
					continue
				}
				for _, proto := range srv.Protocols {
					if proto.Name != "connect" {
						continue
					}
					if scheme := strings.TrimSpace(proto.Scheme); scheme != "" && !strings.EqualFold(scheme, "https") {
						// Only TLS (https) CONNECT upstreams are supported.
						continue
					}
					host, port := proto.Host, proto.Port
					if host == "" {
						host = srv.Hostname
					}
					if port <= 0 {
						port = serverPort
					}
					if host != "" {
						proxies = append(proxies, candidate(host, port))
					}
				}
			}
		}
	}
	return proxies
}

func NormalizeURL(raw string) (*url.URL, error) {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return nil, fmt.Errorf("empty proxy value")
	}
	if !strings.Contains(raw, "://") {
		raw = "https://" + raw
	}
	parsed, err := url.Parse(raw)
	if err != nil {
		return nil, err
	}
	if parsed.Host == "" {
		return nil, fmt.Errorf("missing proxy host")
	}
	return parsed, nil
}
