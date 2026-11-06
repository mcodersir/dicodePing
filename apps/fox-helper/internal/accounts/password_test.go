package accounts

import (
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"dicodeping/fox/internal/fxa"
)

func TestPasswordIsEncryptedAndSurvivesTokenUpdates(t *testing.T) {
	dir := t.TempDir()
	store, err := OpenStore(dir)
	if err != nil {
		t.Fatal(err)
	}
	acc, _, err := store.Add("user@example.com", &fxa.SavedTokens{AccessToken: "a1", RefreshToken: "r1", ObtainedAt: time.Now(), ExpiresIn: 3600}, time.Now())
	if err != nil {
		t.Fatal(err)
	}
	if _, err := store.Password(acc.ID); !errors.Is(err, ErrNoPassword) || store.HasPassword(acc.ID) {
		t.Fatalf("a new account has no password, got %v", err)
	}
	const secret = "correct horse battery staple"
	if err := store.SetPassword(acc.ID, secret); err != nil {
		t.Fatal(err)
	}
	raw, err := os.ReadFile(filepath.Join(dir, "accounts", acc.ID, "credentials.json"))
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(raw), secret) || !strings.Contains(string(raw), `"password": "v1:`) {
		t.Fatalf("the password must be stored encrypted:\n%s", raw)
	}

	// Refreshed tokens keep the password, and the tokens still read back.
	if err := store.SaveCredentials(acc.ID, &fxa.SavedTokens{AccessToken: "a2", RefreshToken: "r2", ObtainedAt: time.Now(), ExpiresIn: 3600}); err != nil {
		t.Fatal(err)
	}
	if got, err := store.Password(acc.ID); err != nil || got != secret {
		t.Fatalf("password after a token update: %q %v", got, err)
	}
	if creds, err := store.Credentials(acc.ID); err != nil || creds.RefreshToken != "r2" {
		t.Fatalf("tokens after setting a password: %+v %v", creds, err)
	}

	// Another key cannot decrypt it.
	if err := os.WriteFile(filepath.Join(dir, "accounts", secretKeyFileName), []byte(strings.Repeat("ab", 32)), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := store.Password(acc.ID); err == nil {
		t.Fatal("a different key must not decrypt the password")
	}
	if err := store.SetPassword(acc.ID, ""); err != nil || store.HasPassword(acc.ID) {
		t.Fatalf("clearing the password: %v", err)
	}
	if list, err := store.List(); err != nil || len(list) != 1 {
		t.Fatalf("the key file must not appear as an account: %v %v", list, err)
	}
}
