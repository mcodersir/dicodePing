package proxy

import (
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"time"

	"dicodeping/fox/internal/logx"
)

type RuntimeStatus struct {
	UpdatedAt          string `json:"updated_at"`
	PID                int    `json:"pid"`
	ProxyPassExpiresAt string `json:"proxy_pass_expires_at"`
	SecondsUntilExpiry int64  `json:"seconds_until_expiry"`
	Accepting          bool   `json:"accepting"`
	Reason             string `json:"reason"`
	// ActiveAccount names the account supplying the ProxyPass in
	// multi-account mode.
	ActiveAccount string `json:"active_account,omitempty"`
	// LastError is a stable failure code of the last renewal attempt
	// (e.g. reauth_required, region_unavailable); empty after success.
	LastError     string `json:"last_error,omitempty"`
	NextAttemptAt string `json:"next_attempt_at,omitempty"`
	// Quota fields are omitted when Guardian sent no valid quota headers.
	QuotaUnlimited      bool   `json:"quota_unlimited,omitempty"`
	QuotaLimitBytes     *int64 `json:"quota_limit_bytes,omitempty"`
	QuotaRemainingBytes *int64 `json:"quota_remaining_bytes,omitempty"`
	QuotaResetAt        string `json:"quota_reset_at,omitempty"`
}

func (c *Controller) CurrentStatus(reason string) RuntimeStatus {
	c.mu.Lock()
	defer c.mu.Unlock()
	status := RuntimeStatus{
		UpdatedAt: time.Now().Format(time.RFC3339),
		PID:       os.Getpid(),
		Reason:    reason,
	}
	if c.current != nil {
		status.ProxyPassExpiresAt = c.current.expiresAt.Format(time.RFC3339)
		status.SecondsUntilExpiry = int64(time.Until(c.current.expiresAt).Round(time.Second) / time.Second)
		status.Accepting = c.current.accepting
	}
	status.LastError = c.lastError
	if c.accounts != nil {
		status.ActiveAccount = c.accounts.ActiveName()
	}
	if !c.nextAttemptAt.IsZero() {
		status.NextAttemptAt = c.nextAttemptAt.Format(time.RFC3339)
	}
	if usage := c.usage; usage != nil {
		if usage.Unlimited {
			status.QuotaUnlimited = true
		} else {
			limit, remaining := usage.Limit, usage.Remaining
			status.QuotaLimitBytes = &limit
			status.QuotaRemainingBytes = &remaining
			if !usage.Reset.IsZero() {
				status.QuotaResetAt = usage.Reset.Format(time.RFC3339)
			}
		}
	}
	return status
}

func (c *Controller) writeStatus(reason string) {
	if c.statusFile == "" {
		return
	}
	status := c.CurrentStatus(reason)
	if err := c.writeStatusFile(status); err != nil {
		logx.Warn("writing status file failed path=%s err=%s", c.statusFile, logx.Err(err))
	}
}

func (c *Controller) writeStatusFile(status RuntimeStatus) error {
	return writeRuntimeStatus(c.statusFile, status)
}

// Status-file reasons written without a controller.
const (
	// StatusSleeping: the proxy listens but holds no upstream session or
	// pass (not connected yet, or asleep after proxy.idle_sleep).
	StatusSleeping = "sleeping"
	// StatusClosed: the proxy stopped.
	StatusClosed = "closed"
)

// WriteIdleStatus writes a status file for a proxy without an upstream
// session: no pass, not accepting, with reason (StatusSleeping or
// StatusClosed).
func WriteIdleStatus(path, reason string) error {
	return writeRuntimeStatus(path, RuntimeStatus{
		UpdatedAt: time.Now().Format(time.RFC3339),
		PID:       os.Getpid(),
		Reason:    reason,
	})
}

// writeRuntimeStatus replaces the status file at path with status; an
// empty path writes nothing.
func writeRuntimeStatus(path string, status RuntimeStatus) error {
	if path == "" {
		return nil
	}
	data, err := json.MarshalIndent(status, "", "  ")
	if err != nil {
		return err
	}
	data = append(data, '\n')

	dir := filepath.Dir(path)
	if err := os.MkdirAll(dir, 0755); err != nil {
		return err
	}
	tmp, err := os.CreateTemp(dir, "."+filepath.Base(path)+".*.tmp")
	if err != nil {
		return err
	}
	tmpName := tmp.Name()
	if _, err := tmp.Write(data); err != nil {
		_ = tmp.Close()
		_ = os.Remove(tmpName)
		return err
	}
	if err := tmp.Close(); err != nil {
		_ = os.Remove(tmpName)
		return err
	}
	if err := os.Rename(tmpName, path); err != nil {
		if removeErr := os.Remove(path); removeErr != nil && !errors.Is(removeErr, os.ErrNotExist) {
			_ = os.Remove(tmpName)
			return err
		}
		if retryErr := os.Rename(tmpName, path); retryErr != nil {
			_ = os.Remove(tmpName)
			return retryErr
		}
	}
	return nil
}
