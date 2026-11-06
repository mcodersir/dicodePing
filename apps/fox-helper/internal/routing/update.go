package routing

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"

	"dicodeping/fox/internal/securefile"
)

// Default list sources, both from Chocolate4U/Iran-v2ray-rules; together
// they cover every region (RegionRules). The domain list has tags such as
// ir, category-ir, cn, geolocation-cn, category-ru, tld-ru, and private;
// the network list has ir, cn, ru, af, tr, id, br, and private.
const (
	DefaultGeoSiteURL = "https://raw.githubusercontent.com/Chocolate4U/Iran-v2ray-rules/release/geosite.dat"
	DefaultGeoIPURL   = "https://raw.githubusercontent.com/Chocolate4U/Iran-v2ray-rules/release/geoip.dat"
)

// Source is a set of the two lists (the ones v2rayNG offers).
type Source struct {
	ID         string `json:"id"`
	Name       string `json:"name"`
	GeoSiteURL string `json:"geosite_url"`
	GeoIPURL   string `json:"geoip_url"`
}

// Sources are the list sets the program offers; both cover every country.
// Checked on 2026-10-15: both network lists have all countries (260 and
// 278 tags); only Chocolate4U's domain list has ir (Loyalsoldier's has
// category-ir), and both have cn, geolocation-cn, category-ru, and tld-ru.
// runetfreedom/russia-v2ray-rules-dat is not offered: 88% of its 74 MB
// domain list are two Russian blocklists that no preset uses.
var Sources = []Source{
	{"chocolate4u", "Chocolate4U", DefaultGeoSiteURL, DefaultGeoIPURL},
	{"loyalsoldier", "Loyalsoldier",
		"https://github.com/Loyalsoldier/v2ray-rules-dat/releases/latest/download/geosite.dat",
		"https://github.com/Loyalsoldier/v2ray-rules-dat/releases/latest/download/geoip.dat"},
}

// RegionSource is the usual list set of region: Loyalsoldier's for China,
// Chocolate4U's otherwise (Iran's rules need its geosite:ir).
func RegionSource(region string) Source {
	id := "chocolate4u"
	if region == RegionChina {
		id = "loyalsoldier"
	}
	for _, s := range Sources {
		if s.ID == id {
			return s
		}
	}
	return Sources[0]
}

// SourceOf finds the offered list set with these URLs.
func SourceOf(geositeURL, geoipURL string) (Source, bool) {
	for _, s := range Sources {
		if s.GeoSiteURL == geositeURL && s.GeoIPURL == geoipURL {
			return s, true
		}
	}
	return Source{}, false
}

// sourceFile records where the two lists in the folder came from, so that
// other URLs download them again although they are not old yet.
const sourceFile = "lists-source.txt"

// SourceChanged reports whether the lists in dir came from other URLs. A
// folder from before the record holds the default lists.
func SourceChanged(dir, geositeURL, geoipURL string) bool {
	data, err := os.ReadFile(filepath.Join(dir, sourceFile))
	if err != nil {
		return geositeURL != DefaultGeoSiteURL || geoipURL != DefaultGeoIPURL
	}
	return strings.TrimSpace(string(data)) != geositeURL+"\n"+geoipURL
}

// maxListSize bounds a downloaded list (the offered ones are 8 to 17 MB).
const maxListSize = 64 << 20

// FileInfo describes a list file in the routing folder.
type FileInfo struct {
	Name      string    `json:"name"`
	Size      int64     `json:"size"`
	UpdatedAt time.Time `json:"updated_at"`
}

// Files describes the list files present in dir, the extra ones too.
func Files(dir string, extras []ExtraFile) []FileInfo {
	var out []FileInfo
	names := []string{GeoSiteFile, GeoIPFile}
	for _, e := range extras {
		names = append(names, e.Name)
	}
	for _, name := range names {
		if info, err := os.Stat(filepath.Join(dir, name)); err == nil {
			out = append(out, FileInfo{Name: name, Size: info.Size(), UpdatedAt: info.ModTime()})
		}
	}
	return out
}

// Due reports whether a list in dir, an extra one too, is missing or older
// than maxAge.
func Due(dir string, maxAge time.Duration, extras []ExtraFile) bool {
	names := []string{GeoSiteFile, GeoIPFile}
	for _, e := range extras {
		names = append(names, e.Name)
	}
	for _, name := range names {
		info, err := os.Stat(filepath.Join(dir, name))
		if err != nil || time.Since(info.ModTime()) >= maxAge {
			return true
		}
	}
	return false
}

// Download fetches both lists with client and replaces the files in dir;
// a file is replaced only when its download is complete and readable as a
// geo list, so a failed update keeps the old one.
func Download(ctx context.Context, client *http.Client, dir, geositeURL, geoipURL string, extras []ExtraFile) error {
	if err := securefile.EnsurePrivateDir(dir); err != nil {
		return err
	}
	var errs []error
	files := []struct{ name, url string }{{GeoSiteFile, geositeURL}, {GeoIPFile, geoipURL}}
	for _, e := range extras {
		files = append(files, struct{ name, url string }{e.Name, e.URL})
	}
	mainFailed := false
	for i, f := range files {
		if err := downloadOne(ctx, client, filepath.Join(dir, f.name), f.url); err != nil {
			errs = append(errs, fmt.Errorf("%s: %w", f.name, err))
			mainFailed = mainFailed || i < 2
		}
	}
	// The record says where both lists came from; without it, or with
	// other URLs, the next check downloads them again.
	record := filepath.Join(dir, sourceFile)
	if mainFailed {
		_ = os.Remove(record)
	} else {
		_ = securefile.WritePrivate(record, []byte(geositeURL+"\n"+geoipURL+"\n"))
	}
	return errors.Join(errs...)
}

func downloadOne(ctx context.Context, client *http.Client, path, url string) error {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return err
	}
	resp, err := client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("HTTP %d from %s", resp.StatusCode, url)
	}
	data, err := io.ReadAll(io.LimitReader(resp.Body, maxListSize+1))
	if err != nil {
		return err
	}
	if len(data) > maxListSize {
		return fmt.Errorf("larger than %d MiB", maxListSize>>20)
	}
	var tags int
	if err := entries(data, func(string) bool { return true }, func(string, []byte) error { tags++; return nil }); err != nil || tags == 0 {
		return fmt.Errorf("not a v2ray geo list (%d tags, %v)", tags, err)
	}
	return securefile.WritePrivate(path, data)
}
