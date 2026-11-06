package serverlist

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"

	"dicodeping/fox/internal/controlplane"
)

// productDetailsURL lists Mozilla's current Firefox versions.
const productDetailsURL = "https://product-details.mozilla.org/1.0/firefox_versions.json"

// LatestFirefoxVersion returns the newest Firefox version Mozilla publishes
// (Nightly, else the release), which every version-gated server-list
// record written for current Firefox accepts.
func LatestFirefoxVersion(ctx context.Context) (string, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, productDetailsURL, nil)
	if err != nil {
		return "", err
	}
	controlplane.ApplyFirefoxHeaders(req)
	resp, err := controlplane.Do(req)
	if err != nil {
		return "", fmt.Errorf("fetching Firefox versions: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return "", fmt.Errorf("Firefox versions returned HTTP %d", resp.StatusCode)
	}
	data, err := io.ReadAll(io.LimitReader(resp.Body, 64<<10))
	if err != nil {
		return "", err
	}
	var versions struct {
		Nightly string `json:"FIREFOX_NIGHTLY"`
		Release string `json:"LATEST_FIREFOX_VERSION"`
	}
	if err := json.Unmarshal(data, &versions); err != nil {
		return "", fmt.Errorf("parsing Firefox versions: %w", err)
	}
	// The release names this program in its User-Agent.
	controlplane.SetFirefoxVersion(versions.Release)
	for _, v := range []string{versions.Nightly, versions.Release} {
		if v = strings.TrimSpace(v); v != "" && v[0] >= '0' && v[0] <= '9' {
			return v, nil
		}
	}
	return "", fmt.Errorf("no Firefox version in the product details")
}
