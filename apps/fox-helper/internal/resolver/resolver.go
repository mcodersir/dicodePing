// Package resolver resolves the host names this program connects to itself
// (Mozilla's Fastly proxy servers and the account, Guardian, and server-list
// APIs) through configurable DNS servers: DNS over HTTPS, DNS over TLS, or
// plain DNS. On filtered networks the system resolver may return wrong
// answers; encrypted DNS avoids that.
//
// Names that SOCKS clients send are not resolved here: they travel inside
// the CONNECT request and Mozilla's exit resolves them.
package resolver

import (
	"context"
	"crypto/tls"
	"errors"
	"fmt"
	"net"
	"net/netip"
	"net/url"
	"slices"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"golang.org/x/net/proxy"

	"dicodeping/fox/internal/egress"
)

const (
	queryTimeout = 5 * time.Second
	minCacheTTL  = 30 * time.Second
	maxCacheTTL  = 10 * time.Minute
	// defaultTTL applies to answers whose TTL is unknown (DoT and plain DNS
	// through Go's resolver).
	defaultTTL = 5 * time.Minute
	// systemAfter is how long the servers have alone before the system is
	// asked too: where a network blocks them they never answer, and its own
	// DNS answers at once.
	systemAfter = time.Second
	// serversDownFor is how long, after the servers all failed, the system
	// is asked at once.
	serversDownFor = time.Minute
	// systemTTL keeps a system answer briefly: the servers may work again.
	systemTTL = time.Minute
)

// iranBlockPageV6 holds the IPv6 addresses of Iran's filtering page (its IPv4
// ones, 10.10.34.34-36, are private).
var iranBlockPageV6 = netip.MustParsePrefix("2001:4188:2:600:10:10:34:0/112")

// IsBlockPage reports whether a public name resolving to addr cannot be its
// real address: a filtering network's answer.
func IsBlockPage(addr netip.Addr) bool {
	addr = addr.Unmap()
	return addr.IsPrivate() || addr.IsLoopback() || addr.IsUnspecified() || addr.IsLinkLocalUnicast() || iranBlockPageV6.Contains(addr)
}

// server answers queries for one configured DNS server.
type server interface {
	lookup(ctx context.Context, host string) ([]netip.Addr, time.Duration, error)
	// lookup6 asks for the IPv6 addresses alone (AAAA).
	lookup6(ctx context.Context, host string) ([]netip.Addr, time.Duration, error)
	// exchange sends a DNS message and returns the reply as it is.
	exchange(ctx context.Context, msg []byte) ([]byte, error)
	String() string
}

// Resolver looks names up through its servers concurrently, uses the first
// answer, caches it, and optionally asks the system resolver too when they are
// slow or fail.
type Resolver struct {
	servers  []server
	fallback bool
	// system is the system resolver.
	system func(ctx context.Context, host string) (Result, error)

	mu    sync.Mutex
	cache map[string]cacheEntry
	// serversFailed is when the servers last all failed; zero once they
	// answer again.
	serversFailed time.Time
}

type cacheEntry struct {
	addrs   []netip.Addr
	source  string
	expires time.Time
}

// New builds a resolver from server specifications:
//
//	https://1.1.1.1/dns-query   DNS over HTTPS
//	tls://1.1.1.1               DNS over TLS (port 853 unless given)
//	udp://8.8.8.8, 8.8.8.8:53   plain DNS (TCP when an answer is truncated)
//
// No servers means the system resolver.
func New(specs []string, fallbackToSystem bool) (*Resolver, error) {
	r := &Resolver{fallback: fallbackToSystem, system: systemLookup, cache: make(map[string]cacheEntry)}
	for _, spec := range specs {
		spec = strings.TrimSpace(spec)
		if spec == "" {
			continue
		}
		s, err := parseServer(spec)
		if err != nil {
			return nil, err
		}
		r.servers = append(r.servers, s)
	}
	return r, nil
}

// Validate reports whether every specification can be parsed.
func Validate(specs []string) error {
	_, err := New(specs, true)
	return err
}

func parseServer(spec string) (server, error) {
	lower := strings.ToLower(spec)
	switch {
	case strings.HasPrefix(lower, "https://"):
		u, err := url.Parse(spec)
		if err != nil || u.Host == "" {
			return nil, fmt.Errorf("invalid DNS-over-HTTPS URL %q", spec)
		}
		if u.Path == "" || u.Path == "/" {
			u.Path = "/dns-query"
		}
		return newDoHServer(u.String()), nil
	case strings.HasPrefix(lower, "tls://"):
		host, port, err := hostPort(spec[len("tls://"):], "853")
		if err != nil {
			return nil, fmt.Errorf("invalid DNS-over-TLS server %q: %w", spec, err)
		}
		return newStreamServer("tls", host, port), nil
	case strings.HasPrefix(lower, "udp://"), strings.HasPrefix(lower, "tcp://"):
		host, port, err := hostPort(spec[len("udp://"):], "53")
		if err != nil {
			return nil, fmt.Errorf("invalid DNS server %q: %w", spec, err)
		}
		if _, err := netip.ParseAddr(host); err != nil {
			return nil, fmt.Errorf("DNS server %q must be an IP address", spec)
		}
		return newStreamServer(lower[:3], host, port), nil
	case strings.Contains(spec, "://"):
		return nil, fmt.Errorf("unsupported DNS server %q (use https://, tls://, udp://, or an IP address)", spec)
	}
	host, port, err := hostPort(spec, "53")
	if err != nil {
		return nil, fmt.Errorf("invalid DNS server %q: %w", spec, err)
	}
	if _, err := netip.ParseAddr(host); err != nil {
		return nil, fmt.Errorf("DNS server %q must be an IP address or a URL", spec)
	}
	return newStreamServer("udp", host, port), nil
}

// hostPort splits "host", "host:port", "[v6]", or "[v6]:port".
func hostPort(s, defaultPort string) (string, string, error) {
	s = strings.TrimSuffix(strings.TrimSpace(s), "/")
	if s == "" {
		return "", "", errors.New("empty address")
	}
	if host, port, err := net.SplitHostPort(s); err == nil {
		return strings.Trim(host, "[]"), port, nil
	}
	if _, err := netip.ParseAddr(s); err == nil {
		return s, defaultPort, nil
	}
	if strings.HasPrefix(s, "[") && strings.HasSuffix(s, "]") {
		return strings.Trim(s, "[]"), defaultPort, nil
	}
	if strings.Contains(s, ":") {
		return "", "", errors.New("bad host:port")
	}
	return s, defaultPort, nil
}

// System reports whether the resolver only uses the system resolver.
func (r *Resolver) System() bool { return r == nil || len(r.servers) == 0 }

// String describes the configuration for logs.
func (r *Resolver) String() string {
	if r.System() {
		return "system"
	}
	names := make([]string, len(r.servers))
	for i, s := range r.servers {
		names[i] = s.String()
	}
	text := strings.Join(names, ", ")
	if r.fallback {
		text += " (system fallback)"
	}
	return text
}

// Result is a lookup outcome with the server that answered.
type Result struct {
	Addrs  []netip.Addr
	Source string
	Cached bool
}

// Lookup resolves host to IP addresses.
func (r *Resolver) Lookup(ctx context.Context, host string) (Result, error) {
	host = strings.TrimSuffix(strings.ToLower(strings.TrimSpace(host)), ".")
	if addr, err := netip.ParseAddr(strings.Trim(host, "[]")); err == nil {
		return Result{Addrs: []netip.Addr{addr}, Source: "literal"}, nil
	}
	if r.System() || host == "localhost" {
		return systemLookup(ctx, host)
	}
	r.mu.Lock()
	if entry, ok := r.cache[host]; ok && time.Now().Before(entry.expires) {
		r.mu.Unlock()
		return Result{Addrs: entry.addrs, Source: entry.source, Cached: true}, nil
	}
	r.mu.Unlock()

	if r.fallback {
		return r.lookupWithSystem(ctx, host)
	}
	result, ttl, err := r.race(ctx, host)
	if err != nil {
		return Result{}, err
	}
	r.remember(host, result, clampTTL(ttl))
	return result, nil
}

func (r *Resolver) remember(host string, result Result, ttl time.Duration) {
	r.mu.Lock()
	r.cache[host] = cacheEntry{addrs: result.Addrs, source: result.Source, expires: time.Now().Add(ttl)}
	r.mu.Unlock()
}

// ipv6Key is a name's cache key for its IPv6 addresses (LookupIPv6).
const ipv6Key = "[ipv6] "

// LookupIPv6 resolves host's IPv6 addresses alone. Lookup asks the servers
// for them only when a name has no IPv4 address; a connection kept to IPv6
// (tcp6, udp6) asks here.
func (r *Resolver) LookupIPv6(ctx context.Context, host string) (Result, error) {
	host = strings.TrimSuffix(strings.ToLower(strings.TrimSpace(host)), ".")
	if addr, err := netip.ParseAddr(strings.Trim(host, "[]")); err == nil {
		return Result{Addrs: KeepFamily("ip6", []netip.Addr{addr}), Source: "literal"}, nil
	}
	if r.System() || host == "localhost" {
		result, err := systemLookup(ctx, host)
		result.Addrs = KeepFamily("ip6", result.Addrs)
		return result, err
	}
	r.mu.Lock()
	if entry, ok := r.cache[ipv6Key+host]; ok && time.Now().Before(entry.expires) {
		r.mu.Unlock()
		return Result{Addrs: entry.addrs, Source: entry.source, Cached: true}, nil
	}
	r.mu.Unlock()
	result, ttl, err := r.raceWith(ctx, host, server.lookup6)
	if err != nil {
		if !r.fallback {
			return Result{}, err
		}
		system, sysErr := r.system(ctx, host)
		if sysErr != nil {
			return Result{}, err
		}
		system.Addrs, system.Source = KeepFamily("ip6", system.Addrs), "system (fallback)"
		return system, nil
	}
	r.remember(ipv6Key+host, result, clampTTL(ttl))
	return result, nil
}

// lookupWithSystem takes the servers' answer, or the system's once they have
// had systemAfter (no wait while they are known to be failing). A block page
// from the system is used only when the servers fail: on a filtering network
// only they can give the real address.
func (r *Resolver) lookupWithSystem(ctx context.Context, host string) (Result, error) {
	type answer struct {
		result Result
		err    error
	}
	servers := make(chan answer, 1)
	go func() {
		// On its own time: though the system answers first, this still tells
		// whether the servers work, and caches their better answer.
		result, ttl, err := r.race(context.WithoutCancel(ctx), host)
		r.mu.Lock()
		if err != nil {
			r.serversFailed = time.Now()
		} else {
			r.serversFailed = time.Time{}
			r.cache[host] = cacheEntry{addrs: result.Addrs, source: result.Source, expires: time.Now().Add(clampTTL(ttl))}
		}
		r.mu.Unlock()
		servers <- answer{result, err}
	}()

	wait := systemAfter
	r.mu.Lock()
	if !r.serversFailed.IsZero() && time.Since(r.serversFailed) < serversDownFor {
		wait = 0
	}
	r.mu.Unlock()
	timer := time.NewTimer(wait)
	defer timer.Stop()

	system := make(chan answer, 1)
	asked := false
	askSystem := func() {
		if asked {
			return
		}
		asked = true
		go func() {
			result, err := r.system(ctx, host)
			result.Source = "system (fallback)"
			system <- answer{result, err}
		}()
	}
	var serversErr error
	var blockPage *Result
	systemDone := false
	for {
		select {
		case a := <-servers:
			servers = nil
			if a.err == nil {
				return a.result, nil
			}
			serversErr = a.err
			if blockPage != nil {
				return *blockPage, nil
			}
			if systemDone {
				return Result{}, serversErr
			}
			askSystem()
		case <-timer.C:
			askSystem()
		case a := <-system:
			systemDone = true
			if a.err != nil {
				if serversErr != nil {
					return Result{}, serversErr
				}
				continue
			}
			if !slices.ContainsFunc(a.result.Addrs, IsBlockPage) {
				r.remember(host, a.result, systemTTL)
				return a.result, nil
			}
			if serversErr != nil {
				return a.result, nil
			}
			blockPage = &a.result
		case <-ctx.Done():
			if serversErr != nil {
				return Result{}, serversErr
			}
			return Result{}, fmt.Errorf("resolving %s: %w", host, ctx.Err())
		}
	}
}

// race queries every server at once and returns the first answer.
func (r *Resolver) race(ctx context.Context, host string) (Result, time.Duration, error) {
	return r.raceWith(ctx, host, server.lookup)
}

// raceWith is race with the servers' lookup of one kind.
func (r *Resolver) raceWith(ctx context.Context, host string, lookup func(server, context.Context, string) ([]netip.Addr, time.Duration, error)) (Result, time.Duration, error) {
	ctx, cancel := context.WithTimeout(ctx, queryTimeout)
	defer cancel()
	type answer struct {
		addrs  []netip.Addr
		ttl    time.Duration
		source string
		err    error
	}
	answers := make(chan answer, len(r.servers))
	for _, s := range r.servers {
		go func(s server) {
			addrs, ttl, err := lookup(s, ctx, host)
			if err == nil && len(addrs) == 0 {
				err = fmt.Errorf("no addresses for %s", host)
			}
			answers <- answer{addrs, ttl, s.String(), err}
		}(s)
	}
	var errs serverErrors
	for range r.servers {
		a := <-answers
		if a.err == nil {
			return Result{Addrs: a.addrs, Source: a.source}, a.ttl, nil
		}
		errs = append(errs, fmt.Errorf("%s: %w", a.source, a.err))
	}
	return Result{}, 0, fmt.Errorf("resolving %s failed: %w", host, errs)
}

// serverErrors are every server's failure, kept as errors so that callers
// can still tell why (proxy.FailureCode: no route is "no network").
type serverErrors []error

func (e serverErrors) Error() string {
	texts := make([]string, len(e))
	for i, err := range e {
		texts[i] = err.Error()
	}
	return strings.Join(texts, "; ")
}

func (e serverErrors) Unwrap() []error { return e }

func clampTTL(ttl time.Duration) time.Duration {
	if ttl <= 0 {
		return defaultTTL
	}
	return min(maxCacheTTL, max(minCacheTTL, ttl))
}

func systemLookup(ctx context.Context, host string) (Result, error) {
	addrs, err := egress.LookupNetIP(ctx, host)
	if err != nil {
		return Result{}, err
	}
	for i := range addrs {
		addrs[i] = addrs[i].Unmap()
	}
	return Result{Addrs: addrs, Source: "system"}, nil
}

// DialContext resolves the host of address and connects to its addresses
// in turn.
func (r *Resolver) DialContext(ctx context.Context, network, address string) (net.Conn, error) {
	return r.dial(ctx, 0, network, address)
}

// DialWithin is DialContext with wait as the limit for connecting, after the
// name is known. The name has its own time, every server's and then the
// system's, so a name the servers are slow to give does not read as a server
// that cannot be reached.
func (r *Resolver) DialWithin(ctx context.Context, wait time.Duration, network, address string) (net.Conn, error) {
	return r.dial(ctx, wait, network, address)
}

// dial connects within wait after the name is known; 0 means ctx alone limits
// it.
func (r *Resolver) dial(ctx context.Context, wait time.Duration, network, address string) (net.Conn, error) {
	d := egress.Dialer(0)
	limit := func() (context.Context, context.CancelFunc) {
		if wait <= 0 {
			return ctx, func() {}
		}
		return context.WithTimeout(ctx, wait)
	}
	if r.System() {
		ctx, cancel := limit()
		defer cancel()
		return d.DialContext(ctx, network, address)
	}
	host, port, err := net.SplitHostPort(address)
	if err != nil {
		return nil, err
	}
	var addrs []netip.Addr
	if strings.HasSuffix(network, "6") {
		result, err := r.LookupIPv6(ctx, host)
		if err != nil {
			return nil, err
		}
		addrs = orderAddrs(result.Addrs)
	} else {
		result, err := r.Lookup(ctx, host)
		if err != nil {
			return nil, err
		}
		addrs = KeepFamily(network, orderAddrs(result.Addrs))
	}
	if len(addrs) == 0 {
		return nil, fmt.Errorf("%s has no %s address", host, familyName(network))
	}
	ctx, cancel := limit()
	defer cancel()
	return dialRace(ctx, d.DialContext, network, port, addrs, dialStagger)
}

// KeepFamily keeps the addresses of network's IP version: IPv4 alone for
// "tcp4", "udp4", and "ip4", IPv6 alone for "tcp6", "udp6", and "ip6", all
// of them else.
func KeepFamily(network string, addrs []netip.Addr) []netip.Addr {
	if !strings.HasSuffix(network, "4") && !strings.HasSuffix(network, "6") {
		return addrs
	}
	v4 := strings.HasSuffix(network, "4")
	out := make([]netip.Addr, 0, len(addrs))
	for _, a := range addrs {
		if a.Unmap().Is4() == v4 {
			out = append(out, a)
		}
	}
	return out
}

func familyName(network string) string {
	if strings.HasSuffix(network, "6") {
		return "IPv6"
	}
	return "IPv4"
}

const (
	// dialStagger is how long a connection waits on one of a name's
	// addresses before it tries the next one too (Happy Eyeballs, RFC 8305).
	// Some networks drop a few of a name's addresses without an answer:
	// waiting on such an address for the whole timeout would fail the
	// sign-in and the pass renewal whenever DNS listed it first.
	dialStagger = 300 * time.Millisecond

	// failedAddrFor is how long an address that refused or failed a
	// connection goes to the end of its name's list.
	failedAddrFor = 10 * time.Minute
)

// failedAddrs maps a netip.Addr to the time until which it goes last.
var failedAddrs sync.Map

func addrFailed(a netip.Addr) bool {
	v, ok := failedAddrs.Load(a)
	if !ok {
		return false
	}
	if time.Now().After(v.(time.Time)) {
		failedAddrs.Delete(a)
		return false
	}
	return true
}

type dialFunc func(ctx context.Context, network, address string) (net.Conn, error)

// dialRace connects to the first of addrs that answers: it starts with the
// first, and starts the next one at once when an attempt fails, or after
// stagger while the earlier ones have not answered. The attempts still
// running when one connects are cancelled, and closed if they connect
// anyway.
func dialRace(ctx context.Context, dial dialFunc, network, port string, addrs []netip.Addr, stagger time.Duration) (net.Conn, error) {
	if len(addrs) == 0 {
		return nil, errors.New("no addresses to connect to")
	}
	ctx, cancel := context.WithCancel(ctx)
	type result struct {
		conn net.Conn
		err  error
		addr netip.Addr
	}
	results := make(chan result, len(addrs))
	started, running := 0, 0
	start := func() {
		a := addrs[started]
		started++
		running++
		go func() {
			conn, err := dial(ctx, network, net.JoinHostPort(a.String(), port))
			results <- result{conn, err, a}
		}()
	}
	finish := func() {
		cancel()
		go func(n int) {
			for ; n > 0; n-- {
				if r := <-results; r.conn != nil {
					r.conn.Close()
				}
			}
		}(running)
	}

	start()
	next := time.NewTimer(stagger)
	defer next.Stop()
	var lastErr error
	for {
		select {
		case r := <-results:
			running--
			if r.err == nil {
				failedAddrs.Delete(r.addr)
				finish()
				return r.conn, nil
			}
			lastErr = r.err
			if ctx.Err() != nil {
				finish()
				return nil, lastErr
			}
			failedAddrs.Store(r.addr, time.Now().Add(failedAddrFor))
			if started < len(addrs) {
				start()
				next.Reset(stagger)
			} else if running == 0 {
				finish()
				return nil, lastErr
			}
		case <-next.C:
			if started < len(addrs) {
				start()
				next.Reset(stagger)
			}
		case <-ctx.Done():
			// The time is up: an attempt still running ends at once, and its
			// error (a dial timeout) is the one to give.
			r := <-results
			running--
			if r.err == nil {
				finish()
				return r.conn, nil
			}
			finish()
			return nil, r.err
		}
	}
}

// orderAddrs puts IPv4 addresses first, IPv6 being often unusable on the
// networks this program targets, and the addresses that failed lately
// last.
func orderAddrs(addrs []netip.Addr) []netip.Addr {
	out := make([]netip.Addr, 0, len(addrs))
	for _, failed := range []bool{false, true} {
		for _, v4 := range []bool{true, false} {
			for _, a := range addrs {
				if a.Is4() == v4 && addrFailed(a) == failed {
					out = append(out, a)
				}
			}
		}
	}
	return out
}

// The process-wide resolver; nil means the system resolver.
var current atomic.Pointer[Resolver]

// Set installs r for every dial in the process; nil restores the system
// resolver.
func Set(r *Resolver) { current.Store(r) }

// Current returns the installed resolver (nil means the system resolver).
func Current() *Resolver { return current.Load() }

// Dial connects through the upstream proxy when one is set, otherwise through
// the installed resolver.
func Dial(ctx context.Context, network, address string) (net.Conn, error) {
	if p := upstream.Load(); p != nil {
		return p.dial.DialContext(ctx, network, address)
	}
	return Current().DialContext(ctx, network, address)
}

// DialWithin is Dial with wait as the limit for connecting, after the name is
// known. Through the upstream proxy only ctx limits it: the proxy reaches the
// server in its own time, and a slow way there is what it is for.
func DialWithin(ctx context.Context, wait time.Duration, network, address string) (net.Conn, error) {
	if p := upstream.Load(); p != nil {
		return p.dial.DialContext(ctx, network, address)
	}
	return Current().DialWithin(ctx, wait, network, address)
}

// upstreamProxy is the user's own SOCKS5 proxy (network.upstream_proxy).
type upstreamProxy struct {
	address string
	dial    proxy.ContextDialer
}

var upstream atomic.Pointer[upstreamProxy]

// proxyForward opens the connection to the upstream proxy itself: a name
// through the installed resolver, and outside a running TUN.
type proxyForward struct{}

func (proxyForward) Dial(network, address string) (net.Conn, error) {
	return Current().DialContext(context.Background(), network, address)
}

func (proxyForward) DialContext(ctx context.Context, network, address string) (net.Conn, error) {
	return Current().DialContext(ctx, network, address)
}

// SetUpstreamProxy sends the connections of Dial and DialWithin through the
// SOCKS5 proxy at address from now on, with the login if username is set; the
// proxy resolves the names they ask for. An empty address connects directly.
func SetUpstreamProxy(address, username, password string) error {
	if address == "" {
		upstream.Store(nil)
		return nil
	}
	var auth *proxy.Auth
	if username != "" {
		auth = &proxy.Auth{User: username, Password: password}
	}
	d, err := proxy.SOCKS5("tcp", address, auth, proxyForward{})
	if err != nil {
		return err
	}
	dial, ok := d.(proxy.ContextDialer)
	if !ok {
		return errors.New("the SOCKS5 dialer cannot take a context")
	}
	upstream.Store(&upstreamProxy{address: address, dial: dial})
	return nil
}

// UpstreamProxy is the address of the upstream proxy in use; "" for none.
func UpstreamProxy() string {
	if p := upstream.Load(); p != nil {
		return p.address
	}
	return ""
}

// LookupNetIP resolves host through the installed resolver, IPv4 first.
func LookupNetIP(ctx context.Context, host string) ([]netip.Addr, error) {
	result, err := Current().Lookup(ctx, host)
	if err != nil {
		return nil, err
	}
	return orderAddrs(result.Addrs), nil
}

// LookupNetIPBoth resolves host's IPv4 and IPv6 addresses at once (the
// IPv6 ones with LookupIPv6) and interleaves them, IPv4 first: the order
// to try them in when both versions are welcome (dual-stack, RFC 8305).
// It fails only when neither version has an address.
func LookupNetIPBoth(ctx context.Context, host string) ([]netip.Addr, error) {
	return Current().lookupBoth(ctx, host)
}

func (r *Resolver) lookupBoth(ctx context.Context, host string) ([]netip.Addr, error) {
	type answer struct {
		addrs []netip.Addr
		err   error
	}
	v6 := make(chan answer, 1)
	go func() {
		result, err := r.LookupIPv6(ctx, host)
		v6 <- answer{result.Addrs, err}
	}()
	result, err4 := r.Lookup(ctx, host)
	a6 := <-v6
	addrs := interleave(KeepFamily("ip4", orderAddrs(result.Addrs)), orderAddrs(a6.addrs))
	if len(addrs) == 0 {
		if err4 != nil {
			return nil, err4
		}
		if a6.err != nil {
			return nil, a6.err
		}
		return nil, fmt.Errorf("no addresses for %s", host)
	}
	return addrs, nil
}

// interleave takes from a and b in turn, a first.
func interleave(a, b []netip.Addr) []netip.Addr {
	out := make([]netip.Addr, 0, len(a)+len(b))
	for i := 0; i < len(a) || i < len(b); i++ {
		if i < len(a) {
			out = append(out, a[i])
		}
		if i < len(b) {
			out = append(out, b[i])
		}
	}
	return out
}

// DialBoth connects over TCP to the first of host's IPv4 and IPv6
// addresses to answer, tried interleaved (LookupNetIPBoth). Through the
// upstream proxy, the proxy picks; with the system resolver, Go's dialer
// tries both versions itself.
func DialBoth(ctx context.Context, address string) (net.Conn, error) {
	if p := upstream.Load(); p != nil {
		return p.dial.DialContext(ctx, "tcp", address)
	}
	r := Current()
	d := egress.Dialer(0)
	if r.System() {
		return d.DialContext(ctx, "tcp", address)
	}
	host, port, err := net.SplitHostPort(address)
	if err != nil {
		return nil, err
	}
	addrs, err := r.lookupBoth(ctx, host)
	if err != nil {
		return nil, err
	}
	return dialRace(ctx, d.DialContext, "tcp", port, addrs, dialStagger)
}

// LookupNetIPFamily is LookupNetIP kept to network's IP version (see
// KeepFamily); the IPv6 addresses come from LookupIPv6.
func LookupNetIPFamily(ctx context.Context, host, network string) ([]netip.Addr, error) {
	if strings.HasSuffix(network, "6") {
		result, err := Current().LookupIPv6(ctx, host)
		if err != nil {
			return nil, err
		}
		return orderAddrs(result.Addrs), nil
	}
	addrs, err := LookupNetIP(ctx, host)
	return KeepFamily(network, addrs), err
}

// streamServer queries a DoT, TCP, or UDP server through Go's resolver,
// which handles truncation, retries, and the wire format.
type streamServer struct {
	kind, host, port string
	r                *net.Resolver
}

func newStreamServer(kind, host, port string) *streamServer {
	s := &streamServer{kind: kind, host: host, port: port}
	s.r = &net.Resolver{PreferGo: true, Dial: func(ctx context.Context, network, _ string) (net.Conn, error) {
		// Go's resolver retries over TCP for a truncated UDP answer.
		if kind == "udp" && !strings.HasPrefix(network, "tcp") {
			return s.dial(ctx, "udp")
		}
		return s.dial(ctx, "tcp")
	}}
	return s
}

// dial connects to the server over UDP, or over a stream: TCP, or TLS for
// DNS over TLS.
func (s *streamServer) dial(ctx context.Context, network string) (net.Conn, error) {
	d := egress.Dialer(0)
	addr := net.JoinHostPort(s.host, s.port)
	if network == "udp" {
		return d.DialContext(ctx, "udp", addr)
	}
	raw, err := d.DialContext(ctx, "tcp", addr)
	if err != nil || s.kind != "tls" {
		return raw, err
	}
	// A TLS connection is a stream, so Go's resolver uses TCP framing on
	// it, which is what DNS over TLS expects.
	conn := tls.Client(raw, &tls.Config{ServerName: s.host, MinVersion: tls.VersionTLS12})
	if err := conn.HandshakeContext(ctx); err != nil {
		_ = raw.Close()
		return nil, err
	}
	return conn, nil
}

func (s *streamServer) lookup(ctx context.Context, host string) ([]netip.Addr, time.Duration, error) {
	addrs, err := s.r.LookupNetIP(ctx, "ip", host)
	for i := range addrs {
		addrs[i] = addrs[i].Unmap()
	}
	return addrs, 0, err
}

func (s *streamServer) lookup6(ctx context.Context, host string) ([]netip.Addr, time.Duration, error) {
	addrs, err := s.r.LookupNetIP(ctx, "ip6", host)
	return addrs, 0, err
}

func (s *streamServer) String() string {
	if s.kind == "udp" && s.port == "53" {
		return s.host
	}
	return s.kind + "://" + net.JoinHostPort(s.host, s.port)
}
