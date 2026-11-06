package fxa

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"

	"dicodeping/fox/internal/controlplane"
)

// DeviceName is how this program appears in the account's connected
// services list.
const DeviceName = "Firefox's built-in VPN"

// deviceType matches Firefox for desktop.
const deviceType = "desktop"

// Device is the device record FxA keeps for a client.
type Device struct {
	ID   string `json:"id"`
	Name string `json:"name"`
	Type string `json:"type"`
}

// RegisterDevice creates (id empty) or renames the device record tied to an
// OAuth refresh token, which is what the Mozilla account's connected
// services page shows for this client. FxA accepts a refresh token as the
// credential for POST /account/device.
func RegisterDevice(ctx context.Context, refreshToken, id, name string) (*Device, error) {
	if refreshToken == "" {
		return nil, fmt.Errorf("%w: no refresh token", ErrReauthRequired)
	}
	body := map[string]string{"name": name, "type": deviceType}
	if id != "" {
		body["id"] = id
	}
	bodyJSON, _ := json.Marshal(body)
	resp, err := fxaDo(ctx, func() (*http.Request, error) {
		req, err := http.NewRequestWithContext(ctx, http.MethodPost, fxaAuthServer+"/account/device", strings.NewReader(string(bodyJSON)))
		if err != nil {
			return nil, err
		}
		req.Header.Set("Content-Type", "application/json")
		req.Header.Set("Authorization", "Bearer "+refreshToken)
		controlplane.ApplyFirefoxHeaders(req)
		return req, nil
	})
	if err != nil {
		return nil, fmt.Errorf("device request: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, newFxaAPIError(resp.StatusCode, []byte(controlplane.ReadErrorBody(resp.Body)))
	}
	data, err := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
	if err != nil {
		return nil, err
	}
	var device Device
	if err := json.Unmarshal(data, &device); err != nil {
		return nil, fmt.Errorf("parsing device response: %w", err)
	}
	if device.ID == "" {
		return nil, fmt.Errorf("device response without an id")
	}
	return &device, nil
}
