// Package accounts stores Firefox Accounts credentials for the multi-account
// daemon and decides which account supplies the ProxyPass: one account is
// active at a time, and the next account in priority order takes over when
// the active one reaches its quota threshold or can no longer be used.
package accounts

import (
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"time"

	"dicodeping/fox/internal/fxa"
	"dicodeping/fox/internal/securefile"
)

const (
	accountsDirName     = "accounts"
	accountFileName     = "account.json"
	credentialsFileName = "credentials.json"
)

// Status is the availability of a stored account.
type Status string

const (
	// StatusReady accounts may supply a ProxyPass.
	StatusReady Status = "ready"
	// StatusReserved accounts reached the switch threshold (or their quota);
	// they become usable again at RetryAt, normally the quota reset.
	StatusReserved Status = "reserved"
	// StatusReauthRequired accounts need a new sign-in.
	StatusReauthRequired Status = "reauth_required"
	// StatusUnavailable accounts were rejected (e.g. not entitled); they
	// are retried at RetryAt.
	StatusUnavailable Status = "unavailable"
)

// Usage is the last known quota state of an account.
type Usage struct {
	Unlimited      bool      `json:"unlimited,omitempty"`
	LimitBytes     int64     `json:"limit_bytes,omitempty"`
	RemainingBytes int64     `json:"remaining_bytes,omitempty"`
	ResetAt        time.Time `json:"reset_at,omitzero"`
	CheckedAt      time.Time `json:"checked_at,omitzero"`
}

// UsedBytes returns the consumed share of the limit.
func (u Usage) UsedBytes() int64 {
	if u.Unlimited {
		return 0
	}
	return u.LimitBytes - u.RemainingBytes
}

// FormatUsage describes u for people, such as "1.2 / 50.0 GiB used,
// resets 2026-01-31"; a nil usage is "unknown".
func FormatUsage(u *Usage) string {
	if u == nil {
		return "unknown"
	}
	if u.Unlimited {
		return "unlimited"
	}
	const gib = 1 << 30
	text := fmt.Sprintf("%.1f / %.1f GiB used", float64(u.UsedBytes())/gib, float64(u.LimitBytes)/gib)
	if !u.ResetAt.IsZero() {
		text += ", resets " + u.ResetAt.Local().Format("2006-01-02")
	}
	return text
}

// Account is the non-secret record of a stored account.
type Account struct {
	ID      string    `json:"id"`
	Email   string    `json:"email,omitempty"`
	Label   string    `json:"label,omitempty"`
	AddedAt time.Time `json:"added_at"`
	Status  Status    `json:"status"`
	// Reason explains the current status in operator terms (English).
	Reason string `json:"reason,omitempty"`
	// ReasonCode names the reason for the apps to put in their own words
	// (the Reason* constants); ReasonDetail is the error it carries, if any.
	ReasonCode   string `json:"reason_code,omitempty"`
	ReasonDetail string `json:"reason_detail,omitempty"`
	// RetryAt is when a reserved or unavailable account may be used again.
	RetryAt time.Time `json:"retry_at,omitzero"`
	Usage   *Usage    `json:"usage,omitempty"`
	// DeviceID is the FxA device record ("Firefox's built-in VPN") of the
	// account's refresh token, and DeviceToken a short fingerprint of that
	// token, so a new sign-in registers a new record.
	DeviceID    string `json:"device_id,omitempty"`
	DeviceToken string `json:"device_token,omitempty"`
}

// AfterReset is the account as it stands at now, for showing it: once its
// quota's reset has passed, the month it last read is over, so nothing of it
// counts and an account set aside for it is back. It takes no request (a core
// at rest asks Mozilla nothing); the next reading brings the real numbers and
// the next reset.
func (a Account) AfterReset(now time.Time) Account {
	u := a.Usage
	if u == nil || u.Unlimited || u.ResetAt.IsZero() || now.Before(u.ResetAt) {
		return a
	}
	if a.Status == StatusReserved && now.Before(a.RetryAt) {
		return a
	}
	fresh := *u
	fresh.RemainingBytes, fresh.ResetAt = fresh.LimitBytes, time.Time{}
	a.Usage = &fresh
	if a.Status == StatusReserved {
		a.Status, a.Reason, a.RetryAt = StatusReady, "", time.Time{}
		a.ReasonCode, a.ReasonDetail = "", ""
	}
	return a
}

// Name returns the most readable identifier of the account.
func (a Account) Name() string {
	switch {
	case a.Label != "":
		return a.Label
	case a.Email != "":
		return a.Email
	default:
		return a.ID
	}
}

// Store keeps one directory per account under <data dir>/accounts: a
// non-secret account.json and an owner-only credentials.json.
type Store struct {
	dir string
	mu  sync.Mutex
}

// OpenStore opens (and creates) the account store inside dataDir.
func OpenStore(dataDir string) (*Store, error) {
	dir := filepath.Join(dataDir, accountsDirName)
	if err := securefile.EnsurePrivateDir(dir); err != nil {
		return nil, fmt.Errorf("creating account store: %w", err)
	}
	return &Store{dir: dir}, nil
}

// Warn receives notices about folders under accounts/ that are skipped;
// the service sends them to the log.
var Warn func(string)

// List returns all stored accounts ordered by the time they were added. A
// folder that is no account (a copy such as "abc - Copy", a damaged or
// empty account file after a crash) is skipped with a warning rather than
// stopping the program: the other accounts keep working, and the folder
// stays for the user.
func (s *Store) List() ([]Account, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	entries, err := os.ReadDir(s.dir)
	if err != nil {
		return nil, err
	}
	var out []Account
	for _, entry := range entries {
		if !entry.IsDir() {
			continue
		}
		acc, err := s.readAccountLocked(entry.Name())
		if errors.Is(err, os.ErrNotExist) {
			continue
		}
		if err != nil {
			if Warn != nil {
				Warn(fmt.Sprintf("skipped the folder accounts/%s, which holds no readable account: %v", entry.Name(), err))
			}
			continue
		}
		out = append(out, acc)
	}
	sort.SliceStable(out, func(i, j int) bool { return out[i].AddedAt.Before(out[j].AddedAt) })
	return out, nil
}

// Get returns one account record.
func (s *Store) Get(id string) (Account, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.readAccountLocked(id)
}

// Save writes an account record.
func (s *Store) Save(acc Account) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.writeAccountLocked(acc)
}

// SaveState stores the fields the account manager owns (status, reason,
// retry time, usage) and keeps the rest of the record as it is on disk.
// The manager holds copies loaded at start; saving a whole copy would
// erase what others wrote since, such as the device record, which then
// made every start register a new "Firefox's built-in VPN" entry.
func (s *Store) SaveState(acc Account) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	current, err := s.readAccountLocked(acc.ID)
	if err != nil {
		return err
	}
	current.Status, current.Reason, current.RetryAt, current.Usage = acc.Status, acc.Reason, acc.RetryAt, acc.Usage
	current.ReasonCode, current.ReasonDetail = acc.ReasonCode, acc.ReasonDetail
	return s.writeAccountLocked(current)
}

// SaveDevice stores the account's device record and keeps the rest of the
// record as it is on disk.
func (s *Store) SaveDevice(id, deviceID, deviceToken string) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	current, err := s.readAccountLocked(id)
	if err != nil {
		return err
	}
	current.DeviceID, current.DeviceToken = deviceID, deviceToken
	return s.writeAccountLocked(current)
}

// Credentials returns the stored OAuth credentials of an account.
func (s *Store) Credentials(id string) (*fxa.SavedTokens, error) {
	if err := validID(id); err != nil {
		return nil, err
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	data, err := os.ReadFile(filepath.Join(s.dir, id, credentialsFileName))
	if err != nil {
		return nil, err
	}
	var creds fxa.SavedTokens
	if err := json.Unmarshal(data, &creds); err != nil {
		return nil, fmt.Errorf("parsing credentials of account %s: %w", id, err)
	}
	if creds.RefreshToken == "" && creds.AccessToken == "" {
		return nil, fmt.Errorf("account %s has no stored credentials", id)
	}
	return &creds, nil
}

// SaveCredentials replaces the stored OAuth credentials of an account.
func (s *Store) SaveCredentials(id string, creds *fxa.SavedTokens) error {
	if err := validID(id); err != nil {
		return err
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.writeCredentialsLocked(id, creds)
}

// Add stores a newly signed-in account. When an account with the same
// email already exists, its credentials are replaced, it becomes ready
// again, and created is false.
func (s *Store) Add(email string, creds *fxa.SavedTokens, now time.Time) (acc Account, created bool, err error) {
	if creds == nil || creds.RefreshToken == "" {
		return Account{}, false, errors.New("a refresh token is required to store an account")
	}
	existing, err := s.List()
	if err != nil {
		return Account{}, false, err
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	email = strings.TrimSpace(email)
	if email != "" {
		for _, candidate := range existing {
			if strings.EqualFold(candidate.Email, email) {
				candidate.Status, candidate.Reason, candidate.RetryAt = StatusReady, "", time.Time{}
				candidate.ReasonCode, candidate.ReasonDetail = "", ""
				if err := s.writeCredentialsLocked(candidate.ID, creds); err != nil {
					return Account{}, false, err
				}
				return candidate, false, s.writeAccountLocked(candidate)
			}
		}
	}
	id, err := newID()
	if err != nil {
		return Account{}, false, err
	}
	acc = Account{ID: id, Email: email, AddedAt: now, Status: StatusReady}
	if err := securefile.EnsurePrivateDir(filepath.Join(s.dir, id)); err != nil {
		return Account{}, false, err
	}
	if err := s.writeCredentialsLocked(id, creds); err != nil {
		return Account{}, false, err
	}
	if err := s.writeAccountLocked(acc); err != nil {
		return Account{}, false, err
	}
	return acc, true, nil
}

// Remove deletes an account and its credentials.
func (s *Store) Remove(id string) error {
	if err := validID(id); err != nil {
		return err
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	return os.RemoveAll(filepath.Join(s.dir, id))
}

func (s *Store) readAccountLocked(id string) (Account, error) {
	if err := validID(id); err != nil {
		return Account{}, err
	}
	data, err := os.ReadFile(filepath.Join(s.dir, id, accountFileName))
	if err != nil {
		return Account{}, err
	}
	var acc Account
	if err := json.Unmarshal(data, &acc); err != nil {
		return Account{}, fmt.Errorf("parsing account %s: %w", id, err)
	}
	if acc.ID != id {
		return Account{}, fmt.Errorf("account file in %s names id %q", id, acc.ID)
	}
	if acc.Status == "" {
		acc.Status = StatusReady
	}
	return acc, nil
}

func (s *Store) writeAccountLocked(acc Account) error {
	if err := validID(acc.ID); err != nil {
		return err
	}
	data, err := json.MarshalIndent(acc, "", "  ")
	if err != nil {
		return err
	}
	return securefile.WritePrivate(filepath.Join(s.dir, acc.ID, accountFileName), append(data, '\n'))
}

// writeCredentialsLocked replaces the tokens and keeps the stored password.
func (s *Store) writeCredentialsLocked(id string, creds *fxa.SavedTokens) error {
	file := credentialsFile{SavedTokens: *creds}
	if old, err := s.readCredentialsFileLocked(id); err == nil {
		file.Password = old.Password
	}
	return s.writeCredentialsFileLocked(id, file)
}

func newID() (string, error) {
	var b [6]byte
	if _, err := rand.Read(b[:]); err != nil {
		return "", err
	}
	return hex.EncodeToString(b[:]), nil
}

// validID rejects ids that could escape the store directory.
func validID(id string) error {
	if id == "" || strings.ContainsAny(id, `/\.:`) {
		return fmt.Errorf("invalid account id %q", id)
	}
	return nil
}
