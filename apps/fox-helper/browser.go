package main

import (
	"context"
	"encoding/hex"
	"strings"
)

// Session is handed over by the official FxA page after the user signs in.
// No password, Guardian JWT or unverified token is substituted for an FxA grant.
func (p *provider) browserLogin(ctx context.Context, email, session string) error {
	session = strings.TrimSpace(session)
	raw, err := hex.DecodeString(session)
	email = strings.TrimSpace(email)
	if err != nil || len(raw) != 32 || len(session) != 64 || len(email) > 254 || !strings.Contains(email, "@") {
		return &ProviderError{Code: "input", Message: "The Mozilla page did not return a valid account session."}
	}
	p.state = State{Email: email, SessionToken: session}
	return p.completeLogin(ctx)
}
