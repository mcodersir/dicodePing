package main

// Protocol adapted from FoxyVPN (MIT, Vauth); see LICENSE-FoxyVPN.txt.
import (
	"bytes"
	"context"
	"crypto/hkdf"
	"crypto/hmac"
	"crypto/pbkdf2"
	"crypto/rand"
	"crypto/sha256"
	"crypto/tls"
	"crypto/x509"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/http/cookiejar"
	"net/url"
	"strconv"
	"strings"
	"sync"
	"time"
)

const authBase = "https://api.accounts.firefox.com/v1"
const guardianBase = "https://vpn.mozilla.org"
const settingsURL = "https://firefox.settings.services.mozilla.com/v1/buckets/main/collections/vpn-serverlist/records"
const clientID = "5882386c6d801776"
const scope = "profile https://identity.mozilla.com/apps/vpn"
const protocol = "identity.mozilla.com/picl/v1/"
const userAgent = "MozillaVPN/2.35.0 (sys:linux; iap:true)"

type AccountInfo struct {
	UID              string `json:"uid,omitempty"`
	Subscribed       bool   `json:"subscribed"`
	LimitedBandwidth bool   `json:"limited_bandwidth"`
	QuotaMax         *int64 `json:"quota_max,omitempty"`
	QuotaRemaining   *int64 `json:"quota_remaining,omitempty"`
	QuotaReset       *int64 `json:"quota_reset,omitempty"`
}
type Location struct {
	CountryCode string `json:"country_code"`
	CountryName string `json:"country_name"`
	CityCode    string `json:"city_code"`
	CityName    string `json:"city_name"`
	Host        string `json:"host"`
	Port        int    `json:"port"`
}
type provider struct {
	roots *x509.CertPool

	state                             State
	client                            *http.Client
	authURL, guardianURL, settingsURL string
	info                              AccountInfo
	mutex                             sync.Mutex
	passRefresh                       chan struct{}
	pass                              string
	passExpiry                        int64
	selected                          Location
	listener                          net.Listener
	streams                           *http.Transport
	bindInterface                     string
	edgeCache                         sync.Map
	edgeResolver                      func(context.Context, string) ([]net.IP, error)
	onState                           func(State)
	onAccount                         func(AccountInfo)
}

func newProvider(s State) *provider {
	jar, _ := cookiejar.New(nil)
	transport := &http.Transport{Proxy: nil, ForceAttemptHTTP2: true, DialContext: (&net.Dialer{Timeout: 15 * time.Second, KeepAlive: 30 * time.Second}).DialContext, TLSHandshakeTimeout: 15 * time.Second, TLSClientConfig: &tls.Config{MinVersion: tls.VersionTLS12}, ResponseHeaderTimeout: 30 * time.Second, IdleConnTimeout: 60 * time.Second}
	return &provider{passRefresh: make(chan struct{}, 1), state: s, authURL: authBase, guardianURL: guardianBase, settingsURL: settingsURL, client: &http.Client{Transport: transport, Jar: jar, CheckRedirect: func(req *http.Request, via []*http.Request) error { return http.ErrUseLastResponse }}}
}
func (p *provider) installRoots(pem string) error {
	if pem == "" {
		return nil
	}
	roots := x509.NewCertPool()
	if !roots.AppendCertsFromPEM([]byte(pem)) {
		return &ProviderError{Code: "trust", Message: "The platform trust store could not be loaded"}
	}
	p.roots = roots
	p.client.Transport.(*http.Transport).TLSClientConfig.RootCAs = roots
	return nil
}
func derivePassword(email, password string) (string, error) {
	quick, err := pbkdf2.Key(sha256.New, password, []byte(protocol+"quickStretch:"+email), 1000, 32)
	if err != nil {
		return "", err
	}
	key, err := hkdf.Key(sha256.New, quick, make([]byte, 32), protocol+"authPW", 32)
	return hex.EncodeToString(key), err
}
func hawk(method, address, session string, body []byte, now int64, nonce string) (string, error) {
	raw, err := hex.DecodeString(session)
	if err != nil || len(raw) != 32 {
		return "", &ProviderError{Code: "session", Message: "Invalid account session"}
	}
	expanded, err := hkdf.Key(sha256.New, raw, make([]byte, 32), protocol+"sessionToken", 64)
	if err != nil {
		return "", err
	}
	u, err := url.Parse(address)
	if err != nil {
		return "", err
	}
	port := u.Port()
	if port == "" {
		port = "443"
	}
	path := u.EscapedPath()
	if u.RawQuery != "" {
		path += "?" + u.RawQuery
	}
	hash := sha256.Sum256(append(append([]byte("hawk.1.payload\napplication/json\n"), body...), '\n'))
	payload := base64.StdEncoding.EncodeToString(hash[:])
	normalized := fmt.Sprintf("hawk.1.header\n%d\n%s\n%s\n%s\n%s\n%s\n%s\n\n", now, nonce, strings.ToUpper(method), path, u.Hostname(), port, payload)
	mac := hmac.New(sha256.New, expanded[32:])
	mac.Write([]byte(normalized))
	return fmt.Sprintf("Hawk id=\"%x\", ts=\"%d\", nonce=\"%s\", mac=\"%s\", hash=\"%s\"", expanded[:32], now, nonce, base64.StdEncoding.EncodeToString(mac.Sum(nil)), payload), nil
}
func (p *provider) request(ctx context.Context, method, address, session, bearer string, body any) (map[string]any, http.Header, error) {
	var data []byte
	var err error
	if body != nil {
		data, err = json.Marshal(body)
		if err != nil {
			return nil, nil, err
		}
	}
	for attempt := 0; attempt < 5; attempt++ {
		req, err := http.NewRequestWithContext(ctx, method, address, bytes.NewReader(data))
		if err != nil {
			return nil, nil, err
		}
		req.Header.Set("User-Agent", userAgent)
		req.Header.Set("Accept", "application/json")
		req.Header.Set("Content-Type", "application/json")
		if session != "" {
			nonce := make([]byte, 6)
			if _, err = rand.Read(nonce); err != nil {
				return nil, nil, err
			}
			v, e := hawk(method, address, session, data, time.Now().Unix(), base64.RawURLEncoding.EncodeToString(nonce))
			if e != nil {
				return nil, nil, e
			}
			req.Header.Set("Authorization", v)
		} else if bearer != "" {
			req.Header.Set("Authorization", "Bearer "+bearer)
		}
		resp, err := p.client.Do(req)
		if err != nil {
			return nil, nil, err
		}
		raw, readErr := io.ReadAll(io.LimitReader(resp.Body, 4*1024*1024))
		resp.Body.Close()
		if readErr != nil {
			return nil, nil, readErr
		}
		if resp.StatusCode == 406 && attempt < 4 {
			if err = p.challenge(ctx); err != nil {
				return nil, nil, err
			}
			continue
		}
		var result map[string]any
		_ = json.Unmarshal(raw, &result)
		if resp.StatusCode >= 300 {
			code, message := "provider", "The provider rejected this request."
			errno := int(number(result["errno"]))
			switch resp.StatusCode {
			case 400:
				code = "input"
				message = "Account sign-in or verification was rejected."
			case 401, 403:
				code = "login_required"
				message = "The account session was rejected. Sign in again."
				if strings.HasPrefix(address, p.guardianURL) {
					code = "activation_required"
					message = "Firefox VPN activation was rejected. Retry activation or sign in again."
				}
			case 406:
				code = "verification_required"
				message = "Mozilla requires browser verification. Complete it in your Mozilla account and try again."
			case 429:
				limited := proxyLimitError(resp.Header)
				code, message = limited.Code, limited.Message
			}
			if errno == 103 {
				code = "credentials"
				message = "Incorrect email or password."
			}
			return nil, resp.Header, &ProviderError{Code: code, Status: resp.StatusCode, Errno: errno, Message: message}
		}
		if result == nil {
			result = map[string]any{}
		}
		return result, resp.Header, nil
	}
	return nil, nil, &ProviderError{Code: "verification_required", Message: "Mozilla account verification is required"}
}
func number(v any) int64 {
	switch x := v.(type) {
	case float64:
		return int64(x)
	case json.Number:
		n, _ := x.Int64()
		return n
	}
	return 0
}
func text(v any) string { s, _ := v.(string); return s }
func (p *provider) login(ctx context.Context, email, password string) error {
	derived, err := derivePassword(email, password)
	if err != nil {
		return err
	}
	body := map[string]any{"email": email, "authPW": derived, "verificationMethod": "email-2fa"}
	data, _, err := p.request(ctx, "POST", p.authURL+"/account/login", "", "", body)
	if api, ok := err.(*ProviderError); ok && api.Errno == 107 {
		delete(body, "verificationMethod")
		data, _, err = p.request(ctx, "POST", p.authURL+"/account/login", "", "", body)
	}
	if err != nil {
		return err
	}
	session := text(data["sessionToken"])
	if session == "" {
		return &ProviderError{Code: "provider", Message: "Mozilla returned no session token"}
	}
	p.state = State{Email: email, SessionToken: session, VerificationMethod: text(data["verificationMethod"])}
	if verified, _ := data["verified"].(bool); verified {
		return p.completeLogin(ctx)
	}
	return nil
}
func (p *provider) verify(ctx context.Context, code string) error {
	if p.state.SessionToken == "" {
		return &ProviderError{Code: "login_required", Message: "Start sign-in first"}
	}
	path := "/session/verify_code"
	if p.state.VerificationMethod == "totp-2fa" || p.state.VerificationMethod == "totp" {
		path = "/session/verify/totp"
	}
	_, _, err := p.request(ctx, "POST", p.authURL+path, p.state.SessionToken, "", map[string]any{"code": code})
	if err != nil {
		return err
	}
	return p.completeLogin(ctx)
}
func (p *provider) completeLogin(ctx context.Context) error {
	data, _, err := p.request(ctx, "POST", p.authURL+"/oauth/token", p.state.SessionToken, "", map[string]any{"client_id": clientID, "grant_type": "fxa-credentials", "scope": scope, "access_type": "offline"})
	if err != nil {
		return err
	}
	if err = p.updateAuth(data); err != nil {
		return err
	}
	p.state.SessionToken = ""
	p.state.VerificationMethod = ""
	return nil
}
func (p *provider) updateAuth(data map[string]any) error {
	token := text(data["access_token"])
	if token == "" {
		return &ProviderError{Code: "provider", Message: "Mozilla returned no access token"}
	}
	p.state.AccessToken = token
	if refresh := text(data["refresh_token"]); refresh != "" {
		p.state.RefreshToken = refresh
	}
	ttl := number(data["expires_in"])
	if ttl <= 0 {
		ttl = 24 * 60 * 60
	}
	p.state.ExpiresAt = time.Now().Unix() + ttl
	if p.onState != nil {
		p.onState(p.state)
	}
	return nil
}
func (p *provider) ensureAuth(ctx context.Context) error {
	if p.state.AccessToken != "" && p.state.ExpiresAt > time.Now().Unix()+120 {
		return nil
	}
	if p.state.RefreshToken == "" {
		return &ProviderError{Code: "login_required", Message: "Sign in to your Mozilla account"}
	}
	data, _, err := p.request(ctx, "POST", p.authURL+"/oauth/token", "", "", map[string]any{"client_id": clientID, "grant_type": "refresh_token", "refresh_token": p.state.RefreshToken, "scope": scope})
	if err != nil {
		return err
	}
	return p.updateAuth(data)
}
func (p *provider) account(ctx context.Context) (AccountInfo, error) {
	p.mutex.Lock()
	defer p.mutex.Unlock()
	if err := p.ensureAuth(ctx); err != nil {
		return AccountInfo{}, err
	}
	// Mint first, like FoxyVPN. Status is metadata, not an eligibility gate.
	// A valid proxy pass is the authoritative connection permission.
	if _, err := p.proxyPassLocked(ctx); err != nil {
		return AccountInfo{}, err
	}
	data, _, err := p.request(ctx, "GET", p.guardianURL+"/api/v1/fpn/status", "", p.state.AccessToken, nil)
	if err == nil {
		p.info.UID = text(data["uid"])
		p.info.Subscribed, _ = data["subscribed"].(bool)
		p.info.LimitedBandwidth, _ = data["limited_bandwidth"].(bool)
		if max, ok := data["maxBytes"]; ok && max != nil && p.info.QuotaMax == nil {
			n := number(max)
			p.info.QuotaMax = &n
		}
	} else if api, ok := err.(*ProviderError); !ok || (api.Status != 401 && api.Status != 403) {
		return AccountInfo{}, err
	}
	return p.info, nil
}
func (p *provider) proxyPassLocked(ctx context.Context) (string, error) {
	if p.info.QuotaRemaining != nil && *p.info.QuotaRemaining <= 0 {
		return "", &ProviderError{Code: "quota_exceeded", Message: "This account has no remaining VPN allowance. Wait for its reset date."}
	}
	if p.pass != "" && p.passExpiry > time.Now().Unix()+60 {
		return p.pass, nil
	}
	if err := p.ensureAuth(ctx); err != nil {
		return "", err
	}
	data, headers, err := p.request(ctx, "GET", p.guardianURL+"/api/v1/fpn/token", "", p.state.AccessToken, nil)
	if api, ok := err.(*ProviderError); ok && (api.Status == 401 || api.Status == 403) {
		// Existing accounts may need Guardian activation even when status
		// advertises limited bandwidth. Never reject before this official step.
		_, _, err = p.request(ctx, "POST", p.guardianURL+"/api/v1/fpn/activate", "", p.state.AccessToken, nil)
		if err == nil {
			data, headers, err = p.request(ctx, "GET", p.guardianURL+"/api/v1/fpn/token", "", p.state.AccessToken, nil)
		}
	}
	if err != nil {
		return "", err
	}
	token := text(data["token"])
	if token == "" {
		return "", &ProviderError{Code: "provider", Message: "Guardian returned no proxy pass"}
	}
	expiry := number(data["expires_at"])
	if expiry <= 0 {
		expiry = jwtExpiry(token)
	}
	if expiry <= 0 {
		expiry = time.Now().Unix() + 300
	}
	p.pass, p.passExpiry = token, expiry
	for header, field := range map[string]**int64{"X-Quota-Limit": &p.info.QuotaMax, "X-Quota-Remaining": &p.info.QuotaRemaining, "X-Quota-Reset": &p.info.QuotaReset} {
		if n, e := strconv.ParseInt(headers.Get(header), 10, 64); e == nil {
			v := n
			*field = &v
		}
	}
	if p.info.QuotaRemaining != nil && *p.info.QuotaRemaining <= 0 {
		return "", &ProviderError{Code: "quota_exceeded", Message: "This account has no remaining VPN allowance. Wait for its reset date."}
	}
	if p.onAccount != nil {
		p.onAccount(p.info)
	}
	return token, nil
}
func jwtExpiry(s string) int64 {
	parts := strings.Split(s, ".")
	if len(parts) < 2 {
		return 0
	}
	raw, e := base64.RawURLEncoding.DecodeString(strings.TrimRight(parts[1], "="))
	if e != nil {
		return 0
	}
	var body map[string]any
	_ = json.Unmarshal(raw, &body)
	return number(body["exp"])
}
func (p *provider) locations(ctx context.Context) ([]Location, error) {
	data, _, err := p.request(ctx, "GET", p.settingsURL, "", "", nil)
	if err != nil {
		return nil, err
	}
	records, _ := data["data"].([]any)
	result := []Location{}
	for _, record := range records {
		r, ok := record.(map[string]any)
		if !ok {
			continue
		}
		c, ok := r["country"].(map[string]any)
		if !ok {
			c = r
		}
		code, name := text(c["code"]), text(c["name"])
		if code == "" || strings.EqualFold(name, "CatchAll Anycast") {
			continue
		}
		cities, _ := c["cities"].([]any)
		for _, rawCity := range cities {
			city, ok := rawCity.(map[string]any)
			if !ok {
				continue
			}
			servers, _ := city["servers"].([]any)
			for _, rawServer := range servers {
				s, ok := rawServer.(map[string]any)
				if !ok {
					continue
				}
				if quarantine, _ := s["quarantined"].(bool); quarantine {
					continue
				}
				host, port := text(s["hostname"]), int(number(s["port"]))
				protocols, _ := s["protocols"].([]any)
				accepted := len(protocols) == 0
				for _, rawProto := range protocols {
					pr, ok := rawProto.(map[string]any)
					if ok && text(pr["name"]) == "connect" {
						accepted = true
						if h := text(pr["host"]); h != "" {
							host = h
						}
						if n := int(number(pr["port"])); n > 0 {
							port = n
						}
						break
					}
				}
				if accepted && host != "" && port > 0 && port <= 65535 {
					result = append(result, Location{CountryCode: code, CountryName: name, CityCode: text(city["code"]), CityName: text(city["name"]), Host: host, Port: port})
				}
			}
		}
	}
	if len(result) == 0 {
		return nil, &ProviderError{Code: "locations", Message: "Mozilla returned no compatible locations"}
	}
	return result, nil
}

// HTTP 429 also means temporary request throttling. Only an explicit zero
// allowance identifies quota exhaustion and may terminate the whole session.
func proxyLimitError(headers http.Header) *ProviderError {
	if remaining, err := strconv.ParseInt(headers.Get("X-Quota-Remaining"), 10, 64); err == nil && remaining <= 0 {
		return &ProviderError{Code: "quota_exceeded", Status: 429, Message: "The provider reports no remaining VPN allowance"}
	}
	return &ProviderError{Code: "rate_limited", Status: 429, Message: "The provider temporarily limited requests; try again shortly"}
}
