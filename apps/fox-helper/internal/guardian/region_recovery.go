package guardian

import (
	"net/http"
	"strings"
	"sync"

	"dicodeping/fox/internal/controlplane"
)

var regionRecovery struct {
	sync.RWMutex
	retry func(*http.Request) (*http.Response, error)
}

// SetRegionRecovery supplies optional recovery only after Guardian HTTP 451.
// It does not replace the shared control-plane transport or its TLS profile.
// A nil response or a failed retry leaves the original 451 response readable.
func SetRegionRecovery(retry func(*http.Request) (*http.Response, error)) {
	regionRecovery.Lock()
	regionRecovery.retry = retry
	regionRecovery.Unlock()
}

func do(req *http.Request) (*http.Response, error) {
	resp, err := controlplane.Do(req)
	if err != nil || resp.StatusCode != http.StatusUnavailableForLegalReasons {
		return resp, err
	}

	// Mozilla's CDN edge refuses the region for the literal Guardian path
	// before the request reaches Guardian. A doubled leading slash does not
	// match that edge rule, while the origin still routes it to the same
	// handler. Try that direct route first, so no relay is needed, and fall
	// back to the configured recovery only if it is still refused.
	if direct, ok := doubledPathRequest(req); ok {
		doubled, doubledErr := controlplane.Do(direct)
		if doubledErr == nil && doubled != nil {
			if doubled.StatusCode != http.StatusUnavailableForLegalReasons {
				resp.Body.Close()
				return doubled, nil
			}
			doubled.Body.Close()
		}
	}

	regionRecovery.RLock()
	retry := regionRecovery.retry
	regionRecovery.RUnlock()
	if retry != nil && req.Context().Err() == nil {
		if recovered, retryErr := retry(req); retryErr == nil && recovered != nil {
			resp.Body.Close()
			return recovered, nil
		}
	}
	return resp, nil
}

// doubledPathRequest clones req with one more leading slash on its path. It
// returns false when the path is already doubled or the body cannot be
// replayed.
func doubledPathRequest(req *http.Request) (*http.Request, bool) {
	if req.URL == nil || !strings.HasPrefix(req.URL.Path, "/") || strings.HasPrefix(req.URL.Path, "//") {
		return nil, false
	}
	if req.Body != nil && req.GetBody == nil {
		return nil, false
	}
	out := req.Clone(req.Context())
	u := *req.URL
	u.Path = "/" + u.Path
	u.RawPath = ""
	out.URL = &u
	if req.GetBody != nil {
		body, err := req.GetBody()
		if err != nil {
			return nil, false
		}
		out.Body = body
	}
	return out, true
}
