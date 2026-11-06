package routing

import (
	"bufio"
	"bytes"
	"context"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"time"

	"dicodeping/fox/internal/securefile"
)

// AppListURL is where a region's phone apps that should connect directly
// come from: hiddify/Android-GFW-Apps, one Android package name per line.
// The lists are GPL-3.0, so they are downloaded, not shipped.
const AppListURL = "https://raw.githubusercontent.com/hiddify/Android-GFW-Apps/master/direct_%s"

// appListRegions are the regions that have a list.
var appListRegions = map[string]bool{RegionIran: true, "cn": true, "ru": true}

// maxAppList bounds a downloaded app list.
const maxAppList = 1 << 20

var packageName = regexp.MustCompile(`^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)+$`)

// HasAppList reports whether region has a list of apps.
func HasAppList(region string) bool { return appListRegions[region] }

// AppListFile is the name of region's app list in the routing folder.
func AppListFile(region string) string { return "apps-direct-" + region + ".txt" }

// AppListDue reports whether region has a list that is missing from dir
// or older than maxAge.
func AppListDue(dir, region string, maxAge time.Duration) bool {
	if !HasAppList(region) {
		return false
	}
	info, err := os.Stat(filepath.Join(dir, AppListFile(region)))
	return err != nil || time.Since(info.ModTime()) >= maxAge
}

// DownloadAppList fetches region's app list with client into dir. The
// file is replaced only by a complete list of package names.
func DownloadAppList(ctx context.Context, client *http.Client, dir, region string) error {
	if !HasAppList(region) {
		return nil
	}
	if err := securefile.EnsurePrivateDir(dir); err != nil {
		return err
	}
	url := fmt.Sprintf(AppListURL, region)
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
	data, err := io.ReadAll(io.LimitReader(resp.Body, maxAppList+1))
	if err != nil {
		return err
	}
	if len(data) > maxAppList {
		return fmt.Errorf("app list larger than %d KiB", maxAppList>>10)
	}
	apps := parseAppList(data)
	if len(apps) == 0 {
		return fmt.Errorf("no package names in %s", url)
	}
	return securefile.WritePrivate(filepath.Join(dir, AppListFile(region)), data)
}

// ReadAppList returns the package names of region's list in dir; none
// when it is missing.
func ReadAppList(dir, region string) []string {
	if !HasAppList(region) {
		return nil
	}
	data, err := os.ReadFile(filepath.Join(dir, AppListFile(region)))
	if err != nil {
		return nil
	}
	return parseAppList(data)
}

// parseAppList keeps the lines that are package names.
func parseAppList(data []byte) []string {
	var apps []string
	scanner := bufio.NewScanner(bytes.NewReader(data))
	for scanner.Scan() {
		if line := bytes.TrimSpace(scanner.Bytes()); packageName.Match(line) {
			apps = append(apps, string(line))
		}
	}
	return apps
}
