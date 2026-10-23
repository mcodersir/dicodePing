package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"os/signal"
	"strings"
	"sync"
	"syscall"
	"time"
)

const version = "4.9.8"

type State struct {
	Email              string `json:"email"`
	AccessToken        string `json:"access_token,omitempty"`
	RefreshToken       string `json:"refresh_token,omitempty"`
	ExpiresAt          int64  `json:"expires_at,omitempty"`
	SessionToken       string `json:"session_token,omitempty"`
	VerificationMethod string `json:"verification_method,omitempty"`
}
type Request struct {
	TLSFragmentation string `json:"tls_fragmentation,omitempty"`
	BindInterface    string `json:"bind_interface,omitempty"`
	Roots            string `json:"ca_bundle,omitempty"`
	Operation        string `json:"operation"`
	Email            string `json:"email,omitempty"`
	Password         string `json:"password,omitempty"`
	Code             string `json:"code,omitempty"`
	Country          string `json:"country,omitempty"`
	Listen           string `json:"listen,omitempty"`
	State            State  `json:"state"`
}
type Response struct {
	OK                bool         `json:"ok"`
	Event             string       `json:"event,omitempty"`
	Error             string       `json:"error,omitempty"`
	Message           string       `json:"message,omitempty"`
	NeedsVerification bool         `json:"needs_verification,omitempty"`
	State             *State       `json:"state,omitempty"`
	Account           *AccountInfo `json:"account,omitempty"`
	Locations         []Location   `json:"locations,omitempty"`
	Country           string       `json:"country,omitempty"`
	Listen            string       `json:"listen,omitempty"`
}
type ProviderError struct {
	Code    string
	Status  int
	Errno   int
	Message string
}

func (e *ProviderError) Error() string { return e.Message }

var outputMu sync.Mutex

func output(v Response) {
	outputMu.Lock()
	defer outputMu.Unlock()
	_ = json.NewEncoder(os.Stdout).Encode(v)
}
func failure(err error) Response {
	r := Response{Error: "network", Message: "Could not reach the provider; check your connection and try again."}
	var p *ProviderError
	if errors.As(err, &p) {
		r.Error = p.Code
		r.Message = p.Message
	}
	if errors.Is(err, context.Canceled) {
		r.Error = "cancelled"
		r.Message = "Cancelled"
	}
	return r
}
func main() {
	if len(os.Args) > 1 && os.Args[1] == "--version" {
		fmt.Println("DicodePing Fox " + version)
		return
	}
	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer cancel()
	reader := json.NewDecoder(io.LimitReader(os.Stdin, 1024*1024))
	var req Request
	if err := reader.Decode(&req); err != nil {
		output(Response{Error: "input", Message: "Invalid private request"})
		os.Exit(2)
	}
	p := newProvider(req.State)
	if req.TLSFragmentation != "" {
		switch req.TLSFragmentation {
		case "sni", "first_byte", "off":
			p.tlsSplit = req.TLSFragmentation
		default:
			output(Response{Error: "input", Message: "Invalid TLS fragmentation mode"})
			os.Exit(2)
		}
	}
	if err := p.bindUplink(req.BindInterface); err != nil {
		output(failure(err))
		os.Exit(2)
	}
	if err := p.installRoots(req.Roots); err != nil {
		output(failure(err))
		os.Exit(2)
	}
	var result Response
	var err error
	opctx, opcancel := context.WithTimeout(ctx, 90*time.Second)
	switch req.Operation {
	case "login":
		if len(req.Email) > 254 || len(req.Password) > 1024 || !strings.Contains(req.Email, "@") {
			err = &ProviderError{Code: "input", Message: "Enter a valid email and password"}
			break
		}
		err = p.login(opctx, strings.TrimSpace(req.Email), req.Password)
		req.Password = ""
		result = Response{OK: err == nil, NeedsVerification: p.state.SessionToken != "", State: &p.state}
	case "verify":
		if len(req.Code) < 4 || len(req.Code) > 16 {
			err = &ProviderError{Code: "input", Message: "Enter the verification code"}
			break
		}
		err = p.verify(opctx, strings.TrimSpace(req.Code))
		result = Response{OK: err == nil, State: &p.state}
	case "status", "refresh":
		var account AccountInfo
		account, err = p.account(opctx)
		result = Response{OK: err == nil, State: &p.state, Account: &account}
	case "locations":
		var locations []Location
		locations, err = p.locations(opctx)
		result = Response{OK: err == nil, Locations: locations}
	case "serve":
		var listener string
		listener, err = p.prepareRelay(opctx, req.Country, req.Listen)
		if err == nil {
			opcancel()
			output(Response{OK: true, Event: "ready", State: &p.state, Account: &p.info, Country: p.selected.CountryCode, Listen: listener})
			p.onState = func(s State) { output(Response{OK: true, Event: "state", State: &s}) }
			p.onAccount = func(info AccountInfo) { output(Response{OK: true, Event: "quota", Account: &info}) }
			// Refresh allowance independently of the active stream. Network failures
			// leave the working tunnel intact; never rewrite the selected profile.
			go func() {
				ticker := time.NewTicker(time.Minute)
				defer ticker.Stop()
				for {
					select {
					case <-ctx.Done():
						return
					case <-ticker.C:
						refreshCtx, finish := context.WithTimeout(ctx, 15*time.Second)
						_ = p.refreshProxyPass(refreshCtx, true)
						finish()
					}
				}
			}()
			// A parent's private pipe closing ends the child, including after a crash.
			go func() {
				var ignored any
				for reader.Decode(&ignored) == nil {
				}
				cancel()
			}()
			err = p.serve(ctx)
			if err != nil && ctx.Err() == nil {
				output(failure(err))
				os.Exit(3)
			}
			return
		}
	default:
		err = &ProviderError{Code: "input", Message: "Unknown helper operation"}
	}
	opcancel()
	if err != nil {
		output(failure(err))
		os.Exit(2)
	}
	output(result)
}
