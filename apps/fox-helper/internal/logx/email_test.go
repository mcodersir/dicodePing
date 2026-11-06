package logx

import "testing"

// An email in a log line keeps only its first letters and the domain,
// unless the log is verbose; a label that is no email stays as it is.
func TestEmail(t *testing.T) {
	defer Verbose.Store(Verbose.Load())
	Verbose.Store(false)
	for in, want := range map[string]string{
		"hamid@yahoo.com": "ha****@yahoo.com",
		"abc@example.com": "a****@example.com",
		"@example.com":    "****@example.com",
		"My second one":   "My second one",
		"":                "",
	} {
		if got := Email(in); got != want {
			t.Fatalf("Email(%q) = %q, want %q", in, got, want)
		}
	}
	Verbose.Store(true)
	if got := Email("hamid@yahoo.com"); got != "hamid@yahoo.com" {
		t.Fatalf("a verbose log shows the whole email, got %q", got)
	}
}
