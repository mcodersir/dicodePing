package controlplane

import (
	"context"
	_ "embed"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/url"
	"os"
	"sort"
	"strings"
	"sync/atomic"
	"time"

	"dicodeping/fox/internal/securefile"
)

//go:embed foxy-default.json
var defaultConfig []byte

type remoteConfig struct {
	Version   int `json:"version"`
	Endpoints struct {
		Guardian     map[string]string `json:"guardian"`
		ControlPlane map[string]string `json:"controlPlane"`
		ServerList   string            `json:"serverList"`
	} `json:"endpoints"`
	Relayers     map[string]string `json:"relayers"`
	Routes       []string          `json:"relayerRoutes"`
	Failover     []int             `json:"failoverCodes"`
	ControlPlane struct {
		Headers map[string]string `json:"headers"`
	} `json:"controlPlane"`
	Guardian struct {
		Headers map[string]string `json:"headers"`
	} `json:"guardian"`
}

var activeRemote atomic.Pointer[remoteConfig]

func parseRemote(data []byte) (*remoteConfig, error) {
	var c remoteConfig
	if len(data) > 256*1024 || json.Unmarshal(data, &c) != nil || c.Version < 1 || len(c.Relayers) == 0 {
		return nil, errors.New("invalid FoxyConfig")
	}
	for _, raw := range c.Relayers {
		if !strings.HasPrefix(raw, "https://") {
			raw = "https://" + raw
		}
		u, e := url.Parse(raw)
		// Relay operators are the two providers shipped by FoxyVPN 2.0.4.
		if e != nil || u.Scheme != "https" || u.User != nil || (u.Host != "relayer.foxyvpn.workers.dev" && u.Host != "relayer.foxyvpn.vercel.app") {
			return nil, errors.New("untrusted relay")
		}
	}
	return &c, nil
}

// ConfigureRemote uses the last valid cache offline, and atomically refreshes
// from the upstream's two HTTPS distribution endpoints at most once per hour.
func ConfigureRemote(cache string) {
	c, _ := parseRemote(defaultConfig)
	if cache != "" {
		if data, e := os.ReadFile(cache); e == nil {
			if saved, e := parseRemote(data); e == nil {
				c = saved
			}
		}
	}
	activeRemote.Store(c)
	if info, e := os.Stat(cache); e == nil && time.Since(info.ModTime()) < time.Hour {
		return
	}
	ctx, cancel := context.WithTimeout(context.Background(), 6*time.Second)
	defer cancel()
	fetch := &http.Client{Transport: QuickTransport(2 * time.Second), Timeout: 3 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	for _, endpoint := range []string{"https://raw.githubusercontent.com/Vauth/FoxyConfig/main/config.json", "https://cdn.jsdelivr.net/gh/Vauth/FoxyConfig@main/config.json"} {
		req, _ := http.NewRequestWithContext(ctx, http.MethodGet, endpoint, nil)
		resp, e := fetch.Do(req)
		if e != nil {
			continue
		}
		data, e := io.ReadAll(io.LimitReader(resp.Body, 256*1024+1))
		resp.Body.Close()
		if e != nil || resp.StatusCode != 200 {
			continue
		}
		next, e := parseRemote(data)
		if e != nil || next.Version < c.Version {
			continue
		}
		activeRemote.Store(next)
		if cache != "" {
			_ = securefile.WritePrivate(cache, data)
		}
		return
	}
}

func remoteCategory(req *http.Request) string {
	switch req.URL.Hostname() {
	case "vpn.mozilla.org":
		if strings.HasPrefix(req.URL.Path, "/api/v1/fpn/") {
			return "guardian"
		}
	case "api.accounts.firefox.com", "oauth.accounts.firefox.com":
		return "fxa"
	case "firefox.settings.services.mozilla.com":
		if strings.Contains(req.URL.Path, "vpn-serverlist") {
			return "server_list"
		}
	}
	return ""
}

func applyRemoteEndpoint(req *http.Request, c *remoteConfig) *http.Request {
	if c == nil {
		return req
	}
	var defaults remoteConfig
	_ = json.Unmarshal(defaultConfig, &defaults)
	target := ""
	for key, original := range defaults.Endpoints.Guardian {
		if req.URL.Scheme+"://"+req.URL.Host+req.URL.Path == original {
			target = c.Endpoints.Guardian[key]
		}
	}
	for key, original := range defaults.Endpoints.ControlPlane {
		if req.URL.Scheme+"://"+req.URL.Host+req.URL.Path == original {
			target = c.Endpoints.ControlPlane[key]
		}
	}
	if req.URL.Scheme+"://"+req.URL.Host+req.URL.Path == defaults.Endpoints.ServerList {
		target = c.Endpoints.ServerList
	}
	if target == "" {
		return req
	}
	u, e := url.Parse(target)
	if e != nil || u.Scheme != "https" || u.User != nil || u.Port() != "" {
		return req
	}
	switch u.Hostname() {
	case "vpn.mozilla.org", "api.accounts.firefox.com", "oauth.accounts.firefox.com", "firefox.settings.services.mozilla.com":
	default:
		return req
	}
	next := req.Clone(req.Context())
	if u.RawQuery == "" {
		u.RawQuery = req.URL.RawQuery
	}
	next.URL = u
	next.Host = ""
	return next
}

func cloneRequest(req *http.Request, ctx context.Context) (*http.Request, error) {
	next := req.Clone(ctx)
	if req.Body != nil && req.Body != http.NoBody {
		if req.GetBody == nil {
			return nil, errors.New("request cannot be replayed")
		}
		var e error
		next.Body, e = req.GetBody()
		if e != nil {
			return nil, e
		}
	}
	return next, nil
}

type cancelBody struct {
	io.ReadCloser
	cancel context.CancelFunc
}

func (b *cancelBody) Close() error { defer b.cancel(); return b.ReadCloser.Close() }

// remoteDo preserves the existing Fox data plane; only blocked control-plane
// requests are retried through the upstream's relayers. Credentials never enter logs.
func remoteDo(req *http.Request) (*http.Response, error) {
	c := activeRemote.Load()
	req = applyRemoteEndpoint(req, c)
	category := remoteCategory(req)
	enabled := false
	if c != nil {
		for _, r := range c.Routes {
			if r == category && category != "" {
				enabled = true
			}
		}
	}
	if !enabled || (req.Body != nil && req.Body != http.NoBody && req.GetBody == nil) {
		return client.Do(req)
	}
	headers := c.ControlPlane.Headers
	if category == "guardian" {
		headers = c.Guardian.Headers
	}
	apply := func(r *http.Request) {
		for k, v := range headers {
			switch strings.ToLower(k) {
			case "user-agent", "accept", "accept-encoding", "cache-control":
				r.Header.Set(k, strings.ReplaceAll(v, "{android_version}", "11"))
			}
		}
	}
	blocked := func(status int) bool {
		for _, v := range c.Failover {
			if v == status {
				return true
			}
		}
		return status == 406 || status == 451
	}
	ctx, cancel := context.WithTimeout(req.Context(), 5*time.Second)
	direct, e := cloneRequest(req, ctx)
	if e != nil {
		cancel()
		return nil, e
	}
	apply(direct)
	resp, err := client.Do(direct)
	if err == nil && !blocked(resp.StatusCode) {
		resp.Body = &cancelBody{resp.Body, cancel}
		return resp, nil
	}
	cancel()
	if resp != nil {
		resp.Body.Close()
	}
	if req.Context().Err() != nil {
		return nil, req.Context().Err()
	}
	names := make([]string, 0, len(c.Relayers))
	for n := range c.Relayers {
		names = append(names, n)
	}
	sort.Strings(names)
	relayClient := *client
	relayClient.Jar = nil
	relayClient.CheckRedirect = func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }
	for _, name := range names {
		relayContext, relayCancel := context.WithTimeout(req.Context(), 8*time.Second)
		next, e := cloneRequest(req, relayContext)
		if e != nil {
			relayCancel()
			return nil, e
		}
		apply(next)
		base := c.Relayers[name]
		if !strings.HasPrefix(base, "https://") {
			base = "https://" + base
		}
		target, _ := url.Parse(base)
		q := target.Query()
		q.Set("url", req.URL.String())
		target.RawQuery = q.Encode()
		next.URL = target
		next.Host = ""
		response, e := relayClient.Do(next)
		if e == nil && response.Header.Get("X-Relay-Error") == "" && !blocked(response.StatusCode) {
			response.Body = &cancelBody{response.Body, relayCancel}
			return response, nil
		}
		relayCancel()
		if response != nil {
			response.Body.Close()
		}
		if e != nil {
			err = e
		}
		if req.Context().Err() != nil {
			return nil, req.Context().Err()
		}
	}
	if err != nil {
		return nil, errors.New("Mozilla direct connection and configured relayers are unavailable")
	}
	return nil, errors.New("Mozilla rejected direct and relayed requests")
}
