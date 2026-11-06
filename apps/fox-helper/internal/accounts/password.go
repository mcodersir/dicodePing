package accounts

import (
	"crypto/aes"
	"crypto/cipher"
	"crypto/rand"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"dicodeping/fox/internal/fxa"
	"dicodeping/fox/internal/securefile"
)

// The Firefox Account password is kept so that an account whose tokens
// were revoked can sign in again without the user typing it. It is
// encrypted with AES-256-GCM under a random key stored next to the
// accounts (secret.key). That keeps it out of plain sight in the JSON
// files; anyone holding the whole data folder can still decrypt it.

const (
	secretKeyFileName = "secret.key"
	passwordPrefix    = "v1:"
)

// ErrNoPassword reports an account without a stored password.
var ErrNoPassword = errors.New("no stored password")

// SetPassword stores the account's password, encrypted, in its credentials
// file. An empty password removes it.
func (s *Store) SetPassword(id, password string) error {
	if err := validID(id); err != nil {
		return err
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	file, err := s.readCredentialsFileLocked(id)
	if err != nil {
		return err
	}
	if password == "" {
		file.Password = ""
	} else {
		key, err := s.secretKeyLocked()
		if err != nil {
			return err
		}
		if file.Password, err = encryptPassword(key, password); err != nil {
			return err
		}
	}
	return s.writeCredentialsFileLocked(id, file)
}

// Password returns the account's stored password, or ErrNoPassword.
func (s *Store) Password(id string) (string, error) {
	if err := validID(id); err != nil {
		return "", err
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	file, err := s.readCredentialsFileLocked(id)
	if err != nil {
		return "", err
	}
	if file.Password == "" {
		return "", ErrNoPassword
	}
	key, err := s.secretKeyLocked()
	if err != nil {
		return "", err
	}
	return decryptPassword(key, file.Password)
}

// HasPassword reports whether the account has a stored password.
func (s *Store) HasPassword(id string) bool {
	if validID(id) != nil {
		return false
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	file, err := s.readCredentialsFileLocked(id)
	return err == nil && file.Password != ""
}

// secretKeyLocked returns the encryption key, creating it on first use.
func (s *Store) secretKeyLocked() ([]byte, error) {
	path := filepath.Join(s.dir, secretKeyFileName)
	data, err := os.ReadFile(path)
	if err == nil {
		key, err := hex.DecodeString(strings.TrimSpace(string(data)))
		if err != nil || len(key) != 32 {
			return nil, fmt.Errorf("%s is damaged; remove it and sign in again", secretKeyFileName)
		}
		return key, nil
	}
	if !errors.Is(err, os.ErrNotExist) {
		return nil, err
	}
	key := make([]byte, 32)
	if _, err := rand.Read(key); err != nil {
		return nil, err
	}
	if err := securefile.WritePrivate(path, []byte(hex.EncodeToString(key)+"\n")); err != nil {
		return nil, err
	}
	return key, nil
}

func encryptPassword(key []byte, password string) (string, error) {
	aead, err := newAEAD(key)
	if err != nil {
		return "", err
	}
	nonce := make([]byte, aead.NonceSize())
	if _, err := rand.Read(nonce); err != nil {
		return "", err
	}
	sealed := aead.Seal(nonce, nonce, []byte(password), nil)
	return passwordPrefix + base64.StdEncoding.EncodeToString(sealed), nil
}

func decryptPassword(key []byte, blob string) (string, error) {
	if !strings.HasPrefix(blob, passwordPrefix) {
		return "", errors.New("unknown password format")
	}
	sealed, err := base64.StdEncoding.DecodeString(strings.TrimPrefix(blob, passwordPrefix))
	if err != nil {
		return "", err
	}
	aead, err := newAEAD(key)
	if err != nil {
		return "", err
	}
	if len(sealed) < aead.NonceSize() {
		return "", errors.New("stored password is damaged")
	}
	plain, err := aead.Open(nil, sealed[:aead.NonceSize()], sealed[aead.NonceSize():], nil)
	if err != nil {
		return "", errors.New("stored password cannot be decrypted (was secret.key replaced?)")
	}
	return string(plain), nil
}

func newAEAD(key []byte) (cipher.AEAD, error) {
	block, err := aes.NewCipher(key)
	if err != nil {
		return nil, err
	}
	return cipher.NewGCM(block)
}

// credentialsFile is the on-disk credentials.json: the OAuth tokens plus
// the encrypted password.
type credentialsFile struct {
	fxa.SavedTokens
	Password string `json:"password,omitempty"`
}

func (s *Store) readCredentialsFileLocked(id string) (credentialsFile, error) {
	var file credentialsFile
	data, err := os.ReadFile(filepath.Join(s.dir, id, credentialsFileName))
	if err != nil {
		return file, err
	}
	if err := json.Unmarshal(data, &file); err != nil {
		return file, fmt.Errorf("parsing credentials of account %s: %w", id, err)
	}
	return file, nil
}

func (s *Store) writeCredentialsFileLocked(id string, file credentialsFile) error {
	data, err := json.MarshalIndent(file, "", "  ")
	if err != nil {
		return err
	}
	return securefile.WritePrivate(filepath.Join(s.dir, id, credentialsFileName), append(data, '\n'))
}
