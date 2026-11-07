package main

import (
	"context"
	"crypto/x509"
	"dicodeping/fox/internal/controlplane"
	"dicodeping/fox/internal/egress"
	"dicodeping/fox/internal/fxa"
	"dicodeping/fox/internal/guardian"
	"dicodeping/fox/internal/hellosplit"
	"dicodeping/fox/internal/proxy"
	"dicodeping/fox/internal/resolver"
	"dicodeping/fox/internal/serverlist"
	"dicodeping/fox/internal/signinproxy"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"os/signal"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"
)

const version = "5.0.0"

type State struct {
	Email              string `json:"email"`
	AccessToken        string `json:"access_token,omitempty"`
	RefreshToken       string `json:"refresh_token,omitempty"`
	ExpiresAt          int64  `json:"expires_at,omitempty"`
	SessionToken       string `json:"session_token,omitempty"`
	VerificationMethod string `json:"verification_method,omitempty"`
}
type Request struct {
	TLSFragmentation string `json:"tls_fragmentation,omitempty"`
	BindInterface    string `json:"bind_interface,omitempty"`
	Roots            string `json:"ca_bundle,omitempty"`
	Operation        string `json:"operation"`
	Email            string `json:"email,omitempty"`
	Password         string `json:"password,omitempty"`
	Code             string `json:"code,omitempty"`
	SessionToken     string `json:"session_token,omitempty"`
	Country          string `json:"country,omitempty"`
	Listen           string `json:"listen,omitempty"`
	State            State  `json:"state"`
}
type Response struct {
	OK                bool         `json:"ok"`
	Event             string       `json:"event,omitempty"`
	Error             string       `json:"error,omitempty"`
	Message           string       `json:"message,omitempty"`
	NeedsVerification bool         `json:"needs_verification,omitempty"`
	State             *State       `json:"state,omitempty"`
	Account           *AccountInfo `json:"account,omitempty"`
	Locations         []Location   `json:"locations,omitempty"`
	Country           string       `json:"country,omitempty"`
	Listen            string       `json:"listen,omitempty"`
}
type ProviderError struct {
	Code    string
	Status  int
	Errno   int
	Message string
}

func (e *ProviderError) Error() string { return e.Message }

var outputMu sync.Mutex

func output(v Response) {
	outputMu.Lock()
	defer outputMu.Unlock()
	_ = json.NewEncoder(os.Stdout).Encode(v)
}

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

func failure(err error) Response {
	r := Response{Error: "network", Message: "Could not reach Mozilla. Check the connection and retry."}
	var p *ProviderError
	if errors.As(err, &p) {
		r.Error = p.Code
		r.Message = p.Message
		return r
	}
	switch {
	case errors.Is(err, context.Canceled):
		r.Error = "cancelled"
		r.Message = "Cancelled"
	case fxa.Errno(err) == 104 || fxa.Errno(err) == 138:
		r.Error = "session_unconfirmed"
		r.Message = "Complete email or two-factor verification in the Mozilla page."
	case fxa.Errno(err) == 102:
		r.Error = "account_not_found"
		r.Message = "No Mozilla account exists for this email."
	case fxa.Errno(err) == 103:
		r.Error = "credentials"
		r.Message = "Incorrect email or password."
	case errors.Is(err, fxa.ErrChallengeBlocked):
		r.Error = "verification_required"
		r.Message = "Mozilla requires verification in the official browser page."
	case errors.Is(err, fxa.ErrReauthRequired):
		r.Error = "login_required"
		r.Message = "Mozilla rejected the saved credential. Sign in again."
	case errors.Is(err, guardian.ErrQuotaExceeded):
		r.Error = "quota_exceeded"
		r.Message = "This account has no remaining VPN allowance."
	case errors.Is(err, guardian.ErrRegionUnavailable):
		r.Error = "region_unavailable"
		r.Message = "Mozilla does not serve the current network region."
	case errors.Is(err, guardian.ErrTokenInvalid):
		r.Error = "activation_required"
		r.Message = "Mozilla refused the account after refresh and activation."
	}
	// Never expose upstream response bodies: OAuth errors may contain secrets.
	return r
}

type engine struct {
	mu        sync.Mutex
	state     State
	streaming bool
}

func (e *engine) snapshot() State { e.mu.Lock(); defer e.mu.Unlock(); return e.state }
func (e *engine) save(t *fxa.TokenResponse) error {
	if t == nil || t.AccessToken == "" || t.ExpiresIn <= 0 {
		return &ProviderError{Code: "provider", Message: "Mozilla returned an invalid account grant."}
	}
	e.mu.Lock()
	e.state.AccessToken = t.AccessToken
	if t.RefreshToken != "" {
		e.state.RefreshToken = t.RefreshToken
	}
	e.state.ExpiresAt = time.Now().Unix() + int64(t.ExpiresIn)
	e.state.SessionToken = ""
	e.state.VerificationMethod = ""
	state, streaming := e.state, e.streaming
	e.mu.Unlock()
	if streaming {
		output(Response{OK: true, Event: "state", State: &state})
	}
	return nil
}
func (e *engine) session(ctx context.Context, email, token string) error {
	raw, err := hex.DecodeString(token)
	if err != nil || len(raw) != 32 || len(email) > 254 || !strings.Contains(email, "@") {
		return &ProviderError{Code: "input", Message: "The Mozilla page did not return a valid session."}
	}
	e.state = State{Email: email, SessionToken: token}
	// Same confirmation and propagation wait as Arman's interactive sign-in.
	for {
		verified, err := fxa.SessionVerified(ctx, token)
		if err == nil && verified {
			break
		}
		if fxa.Errno(err) != 0 {
			return err
		}
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(3 * time.Second):
		}
	}
	var grant *fxa.TokenResponse
	for attempt := 0; ; attempt++ {
		grant, err = fxa.OAuthTokenDirect(ctx, token)
		errno := fxa.Errno(err)
		if err == nil || attempt >= 9 || (errno != 104 && errno != 138) {
			break
		}
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(3 * time.Second):
		}
	}
	if err != nil {
		return err
	}
	return e.save(grant)
}
func (e *engine) auth() *fxa.TokenResponse {
	s := e.snapshot()
	return &fxa.TokenResponse{AccessToken: s.AccessToken, RefreshToken: s.RefreshToken, ExpiresIn: int(s.ExpiresAt - time.Now().Unix()), Scope: "profile https://identity.mozilla.com/apps/vpn", TokenType: "bearer"}
}
func accountUsage(u *guardian.ProxyUsage) AccountInfo {
	info := AccountInfo{}
	if u != nil && !u.Unlimited {
		max, left, reset := u.Limit, u.Remaining, u.Reset.Unix()
		info.QuotaMax = &max
		info.QuotaRemaining = &left
		if reset > 0 {
			info.QuotaReset = &reset
		}
	}
	return info
}
func location(c proxy.Candidate) Location {
	host, port, _ := net.SplitHostPort(c.Addr)
	n, _ := strconv.Atoi(port)
	return Location{c.CountryCode, c.CountryName, c.CityCode, c.CityName, host, n}
}
func configure(req Request) error {
	split := strings.ReplaceAll(req.TLSFragmentation, "_", "-")
	if split == "" {
		split = "sni"
	}
	if !hellosplit.Valid(split) {
		return &ProviderError{Code: "input", Message: "Invalid TLS fragmentation mode"}
	}
	hellosplit.Set(split)
	egress.ExternalControl = interfaceControl(req.BindInterface)
	if req.Roots != "" {
		roots := x509.NewCertPool()
		if !roots.AppendCertsFromPEM([]byte(req.Roots)) {
			return &ProviderError{Code: "trust", Message: "The platform trust store could not be loaded"}
		}
		controlplane.SetRoots(roots)
		proxy.SetUpstreamRoots(roots)
	}
	r, err := resolver.New([]string{"https://1.1.1.1/dns-query", "https://8.8.8.8/dns-query"}, true)
	if err != nil {
		return err
	}
	resolver.Set(r)
	proxy.SetUpstreamIPVersion("auto")
	return nil
}
func probe(ctx context.Context, c *proxy.Controller) bool {
	for _, target := range []struct {
		url, body string
		status    int
	}{{"https://detectportal.firefox.com/success.txt", "success", 200}, {"https://cp.cloudflare.com/generate_204", "", 204}} {
		check, cancel := context.WithTimeout(ctx, 5*time.Second)
		req, _ := http.NewRequestWithContext(check, http.MethodGet, target.url, nil)
		client := c.HTTPClient(5 * time.Second)
		client.CheckRedirect = func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }
		response, err := client.Do(req)
		if err == nil {
			data, readErr := io.ReadAll(io.LimitReader(response.Body, 1024))
			response.Body.Close()
			client.CloseIdleConnections()
			cancel()
			if readErr == nil && response.StatusCode == target.status && strings.TrimSpace(string(data)) == target.body {
				return true
			}
		} else {
			client.CloseIdleConnections()
			cancel()
		}
	}
	return false
}
func run(ctx context.Context, req Request, reader *json.Decoder, cancel context.CancelFunc) error {
	if err := configure(req); err != nil {
		return err
	}
	e := &engine{state: req.State}
	operationTimeout := 95 * time.Second
	if req.Operation == "serve" {
		operationTimeout = 150 * time.Second
	}
	if req.Operation == "browser_login" {
		operationTimeout = 15 * time.Minute
	}
	opctx, finish := context.WithTimeout(ctx, operationTimeout)
	defer finish()
	result := Response{OK: true}
	switch req.Operation {
	case "login":
		if len(req.Email) > 254 || len(req.Password) > 1024 || !strings.Contains(req.Email, "@") {
			return &ProviderError{Code: "input", Message: "Enter a valid email and password"}
		}
		login, err := fxa.Login(opctx, req.Email, req.Password)
		req.Password = ""
		if err != nil {
			return err
		}
		e.state = State{Email: fxa.SignedInEmail(req.Email, login, nil), SessionToken: login.SessionToken, VerificationMethod: login.VerificationMethod}
		if login.Verified && login.VerificationReason == "" {
			grant, err := fxa.OAuthTokenDirect(opctx, login.SessionToken)
			if err != nil {
				return err
			}
			if err = e.save(grant); err != nil {
				return err
			}
		}
		result.NeedsVerification = e.state.SessionToken != ""
	case "browser_login":
		if err := e.session(opctx, req.Email, req.SessionToken); err != nil {
			return err
		}
	case "verify":
		if e.state.SessionToken == "" {
			return &ProviderError{Code: "login_required", Message: "Start sign-in first"}
		}
		var err error
		if strings.HasPrefix(e.state.VerificationMethod, "totp") {
			err = fxa.VerifyTOTP(opctx, e.state.SessionToken, req.Code)
		} else {
			err = fxa.VerifySession(opctx, e.state.SessionToken, req.Code)
		}
		if err != nil {
			return err
		}
		grant, err := fxa.OAuthTokenDirect(opctx, e.state.SessionToken)
		if err != nil {
			return err
		}
		if err = e.save(grant); err != nil {
			return err
		}
	case "signin_proxy":
		server, err := signinproxy.Listen(0, controlplane.DialContext)
		if err != nil {
			return err
		}
		defer server.Close()
		server.Arm()
		output(Response{OK: true, Event: "ready", Listen: server.Addr()})
		finish()
		go func() {
			var ignored any
			for reader.Decode(&ignored) == nil {
			}
			cancel()
		}()
		<-ctx.Done()
		return nil
	case "locations":
		countries, err := serverlist.Fetch(opctx)
		if err != nil {
			return err
		}
		for _, c := range proxy.ConnectCandidates(countries) {
			result.Locations = append(result.Locations, location(c))
		}
		output(result)
		return nil
	case "status", "refresh":
		auth := proxy.DicodeAuth(e.auth(), time.Now(), e.save)
		_, usage, err := proxy.DicodeUsage(opctx, guardian.DefaultEndpoint, auth, true)
		if err != nil {
			return err
		}
		info := accountUsage(usage)
		result.Account = &info
	case "serve":
		auth := proxy.DicodeAuth(e.auth(), time.Now(), e.save)
		fresh, pass, err := proxy.DicodePass(opctx, guardian.DefaultEndpoint, auth)
		if err != nil {
			return err
		}
		info := accountUsage(pass.Usage)
		if req.Operation != "serve" {
			result.Account = &info
			break
		}
		countries, err := serverlist.Fetch(opctx)
		if err != nil {
			return err
		}
		country := strings.ToUpper(strings.TrimSpace(req.Country))
		if country == "" {
			country = "REC"
		}
		candidates := proxy.LocationCandidates(countries, country)
		if country == "REC" {
			for _, c := range proxy.ConnectCandidates(countries) {
				if c.CountryCode != "REC" {
					candidates = append(candidates, c)
				}
			}
		}
		if len(candidates) == 0 {
			return &ProviderError{Code: "unreachable", Message: "Mozilla returned no servers for this location."}
		}
		var controller *proxy.Controller
		for i, candidate := range candidates {
			if i >= 4 {
				break
			}
			if opctx.Err() != nil {
				return opctx.Err()
			}
			target, err := url.Parse("https://" + candidate.Addr)
			if err != nil {
				continue
			}
			// Prefer HTTP/2; networks that interrupt multiplexed sessions get
			// Arman's HTTP/1.1 transport before moving to another server.
			for _, useH1 := range []bool{false, true} {
				controller, err = proxy.NewController(proxy.ControllerConfig{Guardian: guardian.DefaultEndpoint, ProxyURL: target, Timeout: 10 * time.Second, Auth: fresh, Pass: pass, UseH1: useH1, Sessions: 2, ChosenLocation: country != "REC", Server: candidate, Location: candidates, Failover: proxy.NewServerFailover("")})
				if err == nil && probe(opctx, controller) {
					break
				}
				if controller != nil {
					controller.Close()
					controller = nil
				}
				if opctx.Err() != nil {
					return opctx.Err()
				}
			}
			if controller != nil {
				break
			}
		}
		if controller == nil {
			return &ProviderError{Code: "unreachable", Message: "No Firefox VPN server passed the real traffic test. No direct fallback was used."}
		}
		defer controller.Close()
		listen := req.Listen
		if listen == "" {
			listen = "127.0.0.1:0"
		}
		host, _, err := net.SplitHostPort(listen)
		if err != nil || host != "127.0.0.1" {
			return &ProviderError{Code: "input", Message: "Fox helper must listen on IPv4 loopback"}
		}
		ln, err := net.Listen("tcp", listen)
		if err != nil {
			return &ProviderError{Code: "port_in_use", Message: "The Fox SOCKS port is occupied."}
		}
		defer ln.Close()
		e.mu.Lock()
		e.streaming = true
		state := e.state
		e.mu.Unlock()
		output(Response{OK: true, Event: "ready", State: &state, Account: &info, Country: country, Listen: ln.Addr().String()})
		finish()
		go controller.RunRenewalLoop()
		go controller.RunQuotaMonitorLoop()
		go proxy.ServeSOCKS(ln, proxy.NewSOCKSServer(controller, 15*time.Second, 5*time.Minute, 512))
		go func() {
			var ignored any
			for reader.Decode(&ignored) == nil {
			}
			cancel()
		}()
		ticker := time.NewTicker(15 * time.Second)
		defer ticker.Stop()
		for {
			select {
			case <-ctx.Done():
				return nil
			case <-ticker.C:
				status := controller.CurrentStatus("quota")
				info = AccountInfo{QuotaMax: status.QuotaLimitBytes, QuotaRemaining: status.QuotaRemainingBytes}
				if reset, err := time.Parse(time.RFC3339, status.QuotaResetAt); err == nil {
					n := reset.Unix()
					info.QuotaReset = &n
				}
				output(Response{OK: true, Event: "quota", Account: &info})
			}
		}
	default:
		return &ProviderError{Code: "input", Message: "Unknown helper operation"}
	}
	state := e.snapshot()
	result.State = &state
	output(result)
	return nil
}
func main() {
	if len(os.Args) > 1 && os.Args[1] == "--version" {
		fmt.Println("DicodePing Fox " + version + " (Arman VPN v1.0.14)")
		return
	}
	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer cancel()
	reader := json.NewDecoder(io.LimitReader(os.Stdin, 1024*1024))
	var req Request
	if err := reader.Decode(&req); err != nil {
		output(Response{Error: "input", Message: "Invalid private request"})
		os.Exit(2)
	}
	if err := run(ctx, req, reader, cancel); err != nil {
		output(failure(err))
		os.Exit(2)
	}
}
