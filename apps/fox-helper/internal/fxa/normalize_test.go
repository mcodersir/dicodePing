package fxa

import "testing"

func TestNormalizeCode(t *testing.T) {
	for in, want := range map[string]string{
		"۱۲۳۴۵۶":             "123456",
		"١٢٣٤٥٦":             "123456",
		" 123 456 ":          "123456",
		"12\u200c34\u200f56": "123456",
		"\ufeff123456\n":     "123456",
		"۱۲3٤56":             "123456",
		"abcd2345":           "abcd2345",
	} {
		if got := NormalizeCode(in); got != want {
			t.Fatalf("NormalizeCode(%q) = %q, want %q", in, got, want)
		}
	}
}

func TestNormalizeEmail(t *testing.T) {
	for in, want := range map[string]string{
		" User@Example.com ":           "User@Example.com",
		"user\u200c@example.com":       "user@example.com",
		"\u200fuser@example.com\u200e": "user@example.com",
		"user@example.com\u00a0":       "user@example.com",
	} {
		if got := NormalizeEmail(in); got != want {
			t.Fatalf("NormalizeEmail(%q) = %q, want %q", in, got, want)
		}
	}
}
