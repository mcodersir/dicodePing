package fxa

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"testing"
	"testing/synctest"
	"time"

	"dicodeping/fox/internal/controlplane"
)

func TestSolvePowFindsSuffix(t *testing.T) {
	t.Parallel()

	base := "challenge-base-string"
	target := sha256.Sum256([]byte(base + "Xk"))

	answer, ok := solvePow(base, hex.EncodeToString(target[:]))
	if !ok {
		t.Fatal("solvePow did not find a solution")
	}
	if answer != "Xk" {
		t.Fatalf("expected answer Xk, got %q", answer)
	}
}

func TestFxARetriesAfterFinalChallengeWithRecoveryBudget(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		const cookieName = "challenge-retry-fixture"
		const initialTimeout = 15 * time.Second
		const endpoint = fxaAuthServer + "/test-retry"
		var firstDeadline time.Time
		var replayCtx context.Context
		var requests, solves int
		previous := controlplane.Transport()
		t.Cleanup(func() {
			controlplane.SetTransport(previous)
			for _, target := range []string{fxaAuthServer + "/", "https://api.accounts.firefox.com/", "https://oauth.accounts.firefox.com/", fxaSiteURL} {
				u, _ := url.Parse(target)
				controlplane.SetCookies(u, []*http.Cookie{{Name: cookieName, MaxAge: -1}})
			}
		})
		controlplane.SetTransport(roundTripFunc(func(r *http.Request) (*http.Response, error) {
			response := func(status int, body string) *http.Response {
				return &http.Response{StatusCode: status, Header: make(http.Header), Body: io.NopCloser(strings.NewReader(body)), Request: r}
			}
			switch r.URL.Path {
			case "/v1/test-retry":
				requests++
				if requests == 1 {
					firstDeadline, _ = r.Context().Deadline()
					if firstDeadline.Sub(time.Now()) != initialTimeout {
						return nil, errors.New("initial request did not keep its short deadline")
					}
				} else if !time.Now().After(firstDeadline) || r.Context().Err() != nil {
					return nil, errors.New("retry did not use a separate recovery budget")
				}
				if solves < maxChallengeAttempts {
					return response(http.StatusNotAcceptable, ""), nil
				}
				replayCtx = r.Context()
				return response(http.StatusOK, "accepted"), nil
			case "/":
				if _, err := r.Cookie(cookieName); err == nil {
					return response(http.StatusOK, "normal page"), nil
				}
				return response(http.StatusOK, `Client Challenge <script src="/_fs-ch-fixture/script.js"></script>`), nil
			case "/_fs-ch-fixture/script.js":
				return response(http.StatusOK, `init([{"ty":"clientmetrics","data":{}}], "fixture-token", "/_fs-ch-fixture")`), nil
			case "/_fs-ch-fixture/fst-post-back":
				if solves == 0 {
					time.Sleep(initialTimeout + time.Second)
				}
				solves++
				resp := response(http.StatusOK, `{"status":"success"}`)
				resp.Header.Set("Set-Cookie", cookieName+"=cleared; Path=/; Secure")
				return resp, nil
			default:
				return nil, fmt.Errorf("unexpected fixture request to %s", r.URL.Path)
			}
		}))

		ctx := WithRequestTimeout(context.Background(), initialTimeout)
		resp, err := fxaDo(ctx, func() (*http.Request, error) {
			return http.NewRequestWithContext(ctx, http.MethodPost, endpoint, strings.NewReader(`{}`))
		})
		if err != nil {
			t.Fatal(err)
		}
		if replayCtx.Err() != nil {
			t.Fatalf("response body lost its request context: %v", replayCtx.Err())
		}
		data, readErr := io.ReadAll(resp.Body)
		closeErr := resp.Body.Close()
		if readErr != nil || closeErr != nil || string(data) != "accepted" {
			t.Fatalf("reading retry response: body=%q read=%v close=%v", data, readErr, closeErr)
		}
		if replayCtx.Err() != context.Canceled || requests != maxChallengeAttempts+1 || solves != maxChallengeAttempts {
			t.Fatalf("retry context=%v requests=%d solves=%d", replayCtx.Err(), requests, solves)
		}
	})
}

func TestSolvePowRejectsInvalidTarget(t *testing.T) {
	t.Parallel()

	if _, ok := solvePow("base", "not-hex"); ok {
		t.Fatal("expected failure for non-hex target")
	}
	// A hash that does not end on any two-character alphanumeric suffix.
	missing := make([]byte, sha256.Size)
	if _, ok := solvePow("base-that-does-not-match", hex.EncodeToString(missing)); ok {
		t.Fatal("expected no solution for zero hash")
	}
}

func TestParseChallengeInitExtractsToken(t *testing.T) {
	t.Parallel()

	script := `var noise = {init:function(){}};something.init([1,2]);` +
		`;init([{"ty":"pat","data":{}}], "token-abc", "/_fs-ch-1T1wmsGaOgGaSxcX", true);`

	challenges, token, err := parseChallengeInit(script, "/_fs-ch-1T1wmsGaOgGaSxcX")
	if err != nil {
		t.Fatalf("parseChallengeInit returned error: %v", err)
	}
	if token != "token-abc" {
		t.Fatalf("expected token-abc, got %q", token)
	}
	if len(challenges) != 1 || challenges[0].Ty != "pat" {
		t.Fatalf("unexpected challenges: %+v", challenges)
	}
}

func TestParseChallengeInitPowData(t *testing.T) {
	t.Parallel()

	script := `;init([{"ty":"pow","data":{"base":"b","expires":"123","hmac":"h","hash":"00"}}], "tok", "/_fs-ch-x", true);`
	challenges, _, err := parseChallengeInit(script, "/_fs-ch-x")
	if err != nil {
		t.Fatalf("parseChallengeInit returned error: %v", err)
	}
	if len(challenges) != 1 || challenges[0].Ty != "pow" {
		t.Fatalf("unexpected challenges: %+v", challenges)
	}

	var d fastlyPowData
	if err := json.Unmarshal(challenges[0].Data, &d); err != nil {
		t.Fatalf("unmarshalling pow data: %v", err)
	}
	if d.Base != "b" || d.HMAC != "h" || d.Expires != "123" {
		t.Fatalf("unexpected pow data: %+v", d)
	}
}

func TestParseChallengeInitHandlesNestedAndEscapedJSON(t *testing.T) {
	t.Parallel()

	script := `init([{"ty":"pat"}], "older", "/_fs-ch-test");
		init ( [{"ty":"clientmetrics","data":{"nested":[[1,2]],"label":"escaped \" and ]"}}], "tok\u0065n", "\/_fs-ch-test", true);
		init([{"ty":"pat"}], "other", "/_fs-ch-other");`
	challenges, token, err := parseChallengeInit(script, "/_fs-ch-test")
	if err != nil || token != "token" || len(challenges) != 1 || challenges[0].Ty != "clientmetrics" {
		t.Fatalf("did not select the matching nested init call: challenges=%v token=%q err=%v", challenges, token, err)
	}
}

func TestParseChallengeInitLegacyFallback(t *testing.T) {
	t.Parallel()

	script := `init([{"ty":"pat"}], "legacy-token", "/_fs-ch-test" /* legacy script marker */, true);`
	challenges, token, err := parseChallengeInit(script, "/_fs-ch-test")
	if err != nil || token != "legacy-token" || len(challenges) != 1 || challenges[0].Ty != "pat" {
		t.Fatalf("did not read the legacy init call: challenges=%v token=%q err=%v", challenges, token, err)
	}
}

func TestParseChallengeInitRejectsMalformedAndWrongPrefix(t *testing.T) {
	t.Parallel()

	for name, script := range map[string]string{
		"wrong prefix":         `init([{"ty":"pat"}], "token", "/_fs-ch-other");`,
		"legacy wrong prefix":  `init([{"ty":"pat"}], "token", "/_fs-ch-other" /* legacy */, true);`,
		"invalid JSON":         `init([{"ty":"pat",}], "token", "/_fs-ch-test");`,
		"invalid string":       `init([{"ty":"pat"}], "tok\q", "/_fs-ch-test" /* legacy */, true);`,
		"missing type":         `init([{"data":{}}], "token", "/_fs-ch-test" /* legacy */, true);`,
		"empty task list":      `init([], "token", "/_fs-ch-test");`,
		"empty token":          `init([{"ty":"pat"}], "", "/_fs-ch-test");`,
		"expression":           `init([{"ty":"pat"}], "token", "/_fs-ch-test" + other());`,
		"legacy expression":    `init([{"ty":"pat"}], "token", "/_fs-ch-test" /* legacy */ + other());`,
		"incomplete call":      `init([{"ty":"pat"}], "token", "/_fs-ch-test", `,
		"unterminated comment": `init([{"ty":"pat"}], "token", "/_fs-ch-test" /* legacy, true);`,
	} {
		t.Run(name, func(t *testing.T) {
			if _, _, err := parseChallengeInit(script, "/_fs-ch-test"); err == nil {
				t.Fatal("invalid challenge accepted")
			}
		})
	}
}

// A caller waiting for another solve gives up when its context ends, and
// leaves the slot to its holder.
func TestChallengeSlotWaiterGivesUp(t *testing.T) {
	challengeSolveSlot <- struct{}{} // another solve holds the slot
	defer func() { <-challengeSolveSlot }()
	ctx, cancel := context.WithTimeout(context.Background(), 50*time.Millisecond)
	defer cancel()
	start := time.Now()
	if err := solveFastlyChallenge(ctx); !errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("want DeadlineExceeded, got %v", err)
	}
	if waited := time.Since(start); waited > 2*time.Second {
		t.Fatalf("the waiter did not give up in time: %s", waited)
	}
	if len(challengeSolveSlot) != 1 {
		t.Fatal("the waiter must not take or release the holder's slot")
	}
}

// The solver's requests use the same User-Agent and encoding as the API calls.
func TestChallengeRequestsCarryFirefoxHeaders(t *testing.T) {
	type headers struct{ userAgent, encoding string }
	var got []headers
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		got = append(got, headers{r.Header.Get("User-Agent"), r.Header.Get("Accept-Encoding")})
		_, _ = w.Write([]byte(`{"auth":"a"}`))
	}))
	defer server.Close()
	ctx := context.Background()
	if _, err := fetchText(ctx, server.Client(), server.URL+"/"); err != nil {
		t.Fatal(err)
	}
	if _, err := fetchPAT(ctx, server.Client(), server.URL, "token"); err != nil {
		t.Fatal(err)
	}
	if len(got) != 2 {
		t.Fatalf("requests seen: %d", len(got))
	}
	for _, h := range got {
		if h.userAgent != controlplane.FirefoxUserAgent() {
			t.Fatalf("User-Agent %q, want %q", h.userAgent, controlplane.FirefoxUserAgent())
		}
		if h.encoding != "identity" {
			t.Fatalf("Accept-Encoding = %q, want identity", h.encoding)
		}
	}
}
