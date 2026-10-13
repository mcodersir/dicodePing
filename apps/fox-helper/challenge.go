package main

// Bounded Mozilla client challenge, adapted from FoxyVPN (MIT). Interactive verification is never bypassed.
import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"io"
	"net/http"
	"net/url"
	"regexp"
	"strings"
)

var challengePrefix = regexp.MustCompile(`/_fs-ch-[A-Za-z0-9]+`)
var challengeInit = regexp.MustCompile(`init\((\[[^\]]*\]),\s*"([^"]+)",\s*"([^"]+)"`)

const challengeUA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"

func pow(base, target string) (string, bool) {
	expected, e := hex.DecodeString(target)
	if e != nil || len(expected) != 32 {
		return "", false
	}
	alphabet := "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
	for _, a := range alphabet {
		for _, b := range alphabet {
			s := string(a) + string(b)
			hash := sha256.Sum256([]byte(base + s))
			if bytes.Equal(hash[:], expected) {
				return s, true
			}
		}
	}
	return "", false
}
func (p *provider) challengeFetch(ctx context.Context, method, address string, body []byte) ([]byte, int, error) {
	req, e := http.NewRequestWithContext(ctx, method, address, bytes.NewReader(body))
	if e != nil {
		return nil, 0, e
	}
	req.Header.Set("User-Agent", challengeUA)
	req.Header.Set("Accept", "text/html,application/json")
	if method == "POST" {
		req.Header.Set("Content-Type", "application/json")
		u, _ := url.Parse(address)
		req.Header.Set("Origin", u.Scheme+"://"+u.Host)
	}
	resp, e := p.client.Do(req)
	if e != nil {
		return nil, 0, e
	}
	defer resp.Body.Close()
	data, e := io.ReadAll(io.LimitReader(resp.Body, 1024*1024))
	return data, resp.StatusCode, e
}
func (p *provider) challenge(ctx context.Context) error {
	for _, origin := range []string{"https://api.accounts.firefox.com", "https://accounts.firefox.com"} {
		page, status, e := p.challengeFetch(ctx, "GET", origin+"/", nil)
		if e != nil {
			return e
		}
		if status >= 400 || !strings.Contains(string(page), "Client Challenge") {
			continue
		}
		prefix := challengePrefix.FindString(string(page))
		if prefix == "" {
			continue
		}
		base := origin + prefix
		script, status, e := p.challengeFetch(ctx, "GET", base+"/script.js?reload=true", nil)
		if e != nil {
			return e
		}
		if status != 200 {
			continue
		}
		matches := challengeInit.FindAllStringSubmatch(string(script), -1)
		if len(matches) == 0 {
			continue
		}
		m := matches[len(matches)-1]
		var challenges []map[string]any
		if json.Unmarshal([]byte(m[1]), &challenges) != nil {
			continue
		}
		token := m[2]
		for round := 0; round < 3; round++ {
			answers := []map[string]any{}
			for _, ch := range challenges {
				typ := text(ch["ty"])
				data, _ := ch["data"].(map[string]any)
				var answer map[string]any
				switch typ {
				case "pow":
					suffix, ok := pow(text(data["base"]), text(data["hash"]))
					if !ok {
						return &ProviderError{Code: "verification_required", Message: "Mozilla challenge could not be completed"}
					}
					answer = map[string]any{"ty": "pow", "base": data["base"], "answer": suffix, "hmac": data["hmac"], "expires": data["expires"]}
				case "pat":
					raw, status, e := p.challengeFetch(ctx, "POST", base+"/pat?token="+url.QueryEscape(token), nil)
					if e != nil {
						return e
					}
					auth := ""
					if status >= 200 && status < 300 {
						var result map[string]any
						_ = json.Unmarshal(raw, &result)
						auth = text(result["auth"])
					}
					answer = map[string]any{"ty": "pat", "auth": auth}
				case "clientmetrics":
					answer = map[string]any{"ty": "clientmetrics", "webdriver": false, "bot_detection_result": map[string]any{"bot_detected": false, "bot_kind": nil}, "browser_metrics": map[string]any{"client_data": "{}", "error_trace": nil}, "detector_results": map[string]any{}, "v": 2}
				default:
					return &ProviderError{Code: "verification_required", Message: "Mozilla requires interactive verification; complete it in your account before retrying."}
				}
				answers = append(answers, answer)
			}
			body, _ := json.Marshal(map[string]any{"token": token, "data": answers})
			raw, status, e := p.challengeFetch(ctx, "POST", base+"/fst-post-back", body)
			if e != nil {
				return e
			}
			if status != 200 {
				break
			}
			var result map[string]any
			if json.Unmarshal(raw, &result) != nil {
				break
			}
			if text(result["status"]) == "success" {
				confirm, _, e := p.challengeFetch(ctx, "GET", origin+"/", nil)
				if e != nil {
					return e
				}
				if strings.Contains(string(confirm), "Client Challenge") {
					break
				}
				u, _ := url.Parse(origin + "/")
				cookies := p.client.Jar.Cookies(u)
				target, _ := url.Parse("https://api.accounts.firefox.com/")
				for _, c := range cookies {
					c.Domain = "firefox.com"
					c.Path = "/"
					c.Secure = true
				}
				p.client.Jar.SetCookies(target, cookies)
				return nil
			}
			list, ok := result["ch"].([]any)
			token = text(result["tok"])
			if !ok || token == "" {
				break
			}
			challenges = nil
			for _, entry := range list {
				if ch, ok := entry.(map[string]any); ok {
					challenges = append(challenges, ch)
				}
			}
		}
	}
	return &ProviderError{Code: "verification_required", Message: "Mozilla requires browser verification. Complete account verification and retry."}
}
