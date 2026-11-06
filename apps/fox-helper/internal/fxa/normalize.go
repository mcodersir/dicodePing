package fxa

import (
	"strings"
	"unicode"
)

// NormalizeCode cleans a code a person typed or pasted (an emailed
// verification code, an authenticator code, an unblock code): Persian and
// Arabic-Indic digits become ASCII digits, and spaces and invisible
// characters (a zero-width non-joiner, direction marks, a byte-order mark
// from a paste) are dropped. Mozilla accepts only the plain form.
func NormalizeCode(code string) string {
	var b strings.Builder
	for _, r := range code {
		switch {
		case r >= '۰' && r <= '۹': // Persian digits
			b.WriteRune('0' + r - '۰')
		case r >= '٠' && r <= '٩': // Arabic-Indic digits
			b.WriteRune('0' + r - '٠')
		case invisible(r):
		default:
			b.WriteRune(r)
		}
	}
	return b.String()
}

// NormalizeEmail drops spaces and invisible characters from an email a
// person typed or pasted. It does not change letter case: the address is
// part of the password's key derivation, as Mozilla's own clients send it.
func NormalizeEmail(email string) string {
	var b strings.Builder
	for _, r := range email {
		if !invisible(r) {
			b.WriteRune(r)
		}
	}
	return b.String()
}

// invisible reports spaces and format characters (Cf: zero-width joiners,
// direction marks, the byte-order mark).
func invisible(r rune) bool {
	return unicode.IsSpace(r) || unicode.Is(unicode.Cf, r) || unicode.Is(unicode.Zs, r)
}
