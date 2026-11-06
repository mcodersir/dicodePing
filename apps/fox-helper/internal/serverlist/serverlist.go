// Package serverlist reads Mozilla's Remote Settings vpn-serverlist
// collection and applies the record filters Firefox evaluates before
// choosing a proxy location.
package serverlist

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"time"

	"dicodeping/fox/internal/controlplane"
	"dicodeping/fox/internal/securefile"
)

const remoteSettingsURL = "https://firefox.settings.services.mozilla.com/v1/buckets/main/collections/vpn-serverlist/records"

// RecommendedCountryCode is the reserved Remote Settings country code of the
// recommended (anycast) location. Firefox excludes it from the country list
// and uses it as the default location.
const RecommendedCountryCode = "REC"

// DefaultServerPort is the port Firefox assumes when a server record omits it.
const DefaultServerPort = 443

type Protocol struct {
	Name           string `json:"name"`
	Host           string `json:"host"`
	Port           int    `json:"port"`
	Scheme         string `json:"scheme,omitempty"`
	TemplateString string `json:"templateString,omitempty"`
}

type Server struct {
	Hostname    string     `json:"hostname"`
	Port        int        `json:"port"`
	Quarantined bool       `json:"quarantined"`
	Protocols   []Protocol `json:"protocols"`
}

type City struct {
	Name    string   `json:"name"`
	Code    string   `json:"code"`
	Servers []Server `json:"servers"`
}

type Country struct {
	Name   string `json:"name"`
	Code   string `json:"code"`
	Cities []City `json:"cities"`
	// Locked marks a location that Firefox offers only under
	// preconditions (e.g. an upgraded account). The program offers every
	// location regardless: Mozilla's servers accept an ordinary account's
	// pass on locked ones too. It is shown only in the server-list dump.
	Locked bool `json:"locked,omitempty"`
	// FilterExpression is the Remote Settings JEXL filter that decides
	// whether this record applies to a client (Firefox version, region).
	FilterExpression string `json:"filter_expression,omitempty"`
}

type remoteSettingsResponse struct {
	Data []json.RawMessage `json:"data"`
}

func fetchServerList(ctx context.Context) ([]Country, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, remoteSettingsURL, nil)
	if err != nil {
		return nil, err
	}
	controlplane.ApplyFirefoxHeaders(req)

	resp, err := controlplane.Do(req)
	if err != nil {
		return nil, fmt.Errorf("fetching server list: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("server list returned HTTP %d: %s", resp.StatusCode, controlplane.ReadErrorBody(resp.Body))
	}

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("reading server list response: %w", err)
	}

	var rsResp remoteSettingsResponse
	if err := json.Unmarshal(body, &rsResp); err != nil {
		return nil, fmt.Errorf("parsing server list envelope: %w", err)
	}

	var countries []Country
	for _, raw := range rsResp.Data {
		var c Country
		if err := json.Unmarshal(raw, &c); err != nil {
			// If it doesn't parse as a Country, skip it
			continue
		}
		if c.Code != "" && len(c.Cities) > 0 {
			countries = append(countries, c)
		}
	}

	return countries, nil
}

func printServerList(countries []Country) {
	for _, country := range countries {
		flags := ""
		if country.Code == RecommendedCountryCode {
			flags += " [RECOMMENDED]"
		}
		if country.Locked {
			flags += " [locked in Firefox]"
		}
		fmt.Printf("\n=== %s (%s)%s ===\n", country.Name, country.Code, flags)
		for _, city := range country.Cities {
			fmt.Printf("  City: %s (%s)\n", city.Name, city.Code)
			for _, srv := range city.Servers {
				port := srv.Port
				if port <= 0 {
					port = DefaultServerPort
				}
				if srv.Quarantined {
					fmt.Printf("    [QUARANTINED] %s:%d\n", srv.Hostname, port)
					continue
				}
				fmt.Printf("    Server: %s:%d\n", srv.Hostname, port)
				for _, proto := range srv.Protocols {
					switch proto.Name {
					case "connect":
						scheme := proto.Scheme
						if scheme == "" {
							scheme = "https"
						}
						fmt.Printf("      Protocol: CONNECT (%s) -> %s:%d\n", scheme, proto.Host, proto.Port)
					case "masque":
						fmt.Printf("      Protocol: MASQUE -> %s:%d (template: %s)\n", proto.Host, proto.Port, proto.TemplateString)
					default:
						fmt.Printf("      Protocol: %s -> %s:%d\n", proto.Name, proto.Host, proto.Port)
					}
				}

				if len(srv.Protocols) == 0 {
					fmt.Printf("      Protocol: CONNECT (https) -> %s:%d (default)\n", srv.Hostname, port)
				}
			}
		}
	}
}

func Fetch(ctx context.Context) ([]Country, error) {
	return fetchServerList(ctx)
}

// cacheFile is the saved list: the records as fetched (before Filter, which
// runs again for the Firefox version of the day) and when.
type cacheFile struct {
	SavedAt   time.Time `json:"saved_at"`
	Countries []Country `json:"countries"`
}

// SaveCache keeps a fetched list in path. The list changes rarely; the
// copy lets the program show the locations at once and connect when the
// next fetch fails (Mozilla's settings server unreachable).
func SaveCache(path string, countries []Country) error {
	data, err := json.Marshal(cacheFile{SavedAt: time.Now().UTC(), Countries: countries})
	if err != nil {
		return err
	}
	return securefile.WritePrivate(path, data)
}

// LoadCache reads the list SaveCache kept, and when it was saved.
func LoadCache(path string) ([]Country, time.Time, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, time.Time{}, err
	}
	var file cacheFile
	if err := json.Unmarshal(data, &file); err != nil {
		return nil, time.Time{}, fmt.Errorf("reading %s: %w", path, err)
	}
	if len(file.Countries) == 0 {
		return nil, time.Time{}, fmt.Errorf("%s holds no locations", path)
	}
	return file.Countries, file.SavedAt, nil
}

func Print(countries []Country) {
	printServerList(countries)
}
