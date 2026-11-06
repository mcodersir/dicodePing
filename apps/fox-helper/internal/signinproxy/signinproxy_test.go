package signinproxy

import (
	"bufio"
	"context"
	"errors"
	"io"
	"net"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"testing"
	"time"
)

func TestAllowed(t *testing.T) {
	for host, want := range map[string]bool{
		"accounts.firefox.com":      true,
		"api.accounts.firefox.com":  true,
		"API.Accounts.Firefox.com.": true,
		"firefox.com":               true,
		"cdn.mozilla.net":           true,
		"accounts.google.com":       true,
		"appleid.apple.com":         true,
		"notfirefox.com":            false,
		"firefox.com.example.net":   false,
		"storage.googleapis.com":    false,
		"example.com":               false,
		"127.0.0.1":                 false,
		"151.101.129.91":            false,
		"::1":                       false,
		"":                          false,
	} {
		if got := Allowed(host); got != want {
			t.Errorf("Allowed(%q) = %v, want %v", host, got, want)
		}
	}
}

// echoDial answers every connection with an echo of what it gets, and
// records the addresses asked for.
func echoDial(asked chan<- string) DialFunc {
	return func(ctx context.Context, network, address string) (net.Conn, error) {
		asked <- address
		client, server := net.Pipe()
		go func() {
			defer server.Close()
			io.Copy(server, server)
		}()
		return client, nil
	}
}

// connect sends a CONNECT for target and returns the status line's code
// and the connection, positioned after the response head.
func connect(t *testing.T, addr, target string) (int, net.Conn, *bufio.Reader) {
	t.Helper()
	c, err := net.Dial("tcp", addr)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { c.Close() })
	c.SetDeadline(time.Now().Add(5 * time.Second))
	if _, err := io.WriteString(c, "CONNECT "+target+" HTTP/1.1\r\nHost: "+target+"\r\n\r\n"); err != nil {
		t.Fatal(err)
	}
	br := bufio.NewReader(c)
	resp, err := http.ReadResponse(br, &http.Request{Method: http.MethodConnect})
	if err != nil {
		t.Fatal(err)
	}
	return resp.StatusCode, c, br
}

func TestServesSignInHostsOnlyWhileArmed(t *testing.T) {
	asked := make(chan string, 4)
	s, err := Listen(0, echoDial(asked))
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	if !strings.HasPrefix(s.Addr(), "127.0.0.1:") {
		t.Fatalf("Addr() = %q, want loopback", s.Addr())
	}

	if code, _, _ := connect(t, s.Addr(), "api.accounts.firefox.com:443"); code != http.StatusForbidden {
		t.Fatalf("disarmed: status %d, want 403", code)
	}

	s.Arm()
	code, c, br := connect(t, s.Addr(), "api.accounts.firefox.com:443")
	if code != http.StatusOK {
		t.Fatalf("armed: status %d, want 200", code)
	}
	if got := <-asked; got != "api.accounts.firefox.com:443" {
		t.Fatalf("dialed %q", got)
	}
	if _, err := io.WriteString(c, "hello"); err != nil {
		t.Fatal(err)
	}
	buf := make([]byte, 5)
	if _, err := io.ReadFull(br, buf); err != nil || string(buf) != "hello" {
		t.Fatalf("tunnel echo = %q, %v", buf, err)
	}

	for _, target := range []string{"example.com:443", "accounts.firefox.com:80", "127.0.0.1:10820"} {
		if code, _, _ := connect(t, s.Addr(), target); code != http.StatusForbidden {
			t.Errorf("%s: status %d, want 403", target, code)
		}
	}
	select {
	case got := <-asked:
		t.Fatalf("dialed %q for a refused destination", got)
	default:
	}
}

func TestDisarmClosesOpenTunnels(t *testing.T) {
	s, err := Listen(0, echoDial(make(chan string, 1)))
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	s.Arm()
	_, c, br := connect(t, s.Addr(), "accounts.firefox.com:443")
	s.Disarm()
	if _, err := br.ReadByte(); err == nil {
		t.Fatal("tunnel still open after Disarm")
	}
	c.Close()
}

func TestArmExpires(t *testing.T) {
	s, err := Listen(0, echoDial(make(chan string, 1)))
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	now := time.Now()
	s.now = func() time.Time { return now }
	s.Arm()
	now = now.Add(ArmFor + time.Second)
	if code, _, _ := connect(t, s.Addr(), "accounts.firefox.com:443"); code != http.StatusForbidden {
		t.Fatalf("status %d after the arm ran out, want 403", code)
	}
}

func TestFailedDialAnswersBadGateway(t *testing.T) {
	s, err := Listen(0, func(context.Context, string, string) (net.Conn, error) {
		return nil, errors.New("no route")
	})
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	s.Arm()
	if code, _, _ := connect(t, s.Addr(), "accounts.firefox.com:443"); code != http.StatusBadGateway {
		t.Fatalf("status %d, want 502", code)
	}
}

func TestNotConnectRefused(t *testing.T) {
	s, err := Listen(0, echoDial(make(chan string, 1)))
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	s.Arm()
	resp, err := (&http.Client{Transport: &http.Transport{Proxy: http.ProxyURL(mustURL(t, "http://"+s.Addr()))}}).Get("http://accounts.firefox.com/")
	if err != nil {
		t.Fatal(err)
	}
	resp.Body.Close()
	if resp.StatusCode != http.StatusMethodNotAllowed {
		t.Fatalf("status %d, want 405", resp.StatusCode)
	}
}

func mustURL(t *testing.T, raw string) *url.URL {
	t.Helper()
	u, err := url.Parse(raw)
	if err != nil {
		t.Fatal(err)
	}
	return u
}

func TestListenTakesThePreferredPort(t *testing.T) {
	first, err := Listen(0, echoDial(make(chan string, 1)))
	if err != nil {
		t.Fatal(err)
	}
	_, port, _ := net.SplitHostPort(first.Addr())
	first.Close()
	p, _ := strconv.Atoi(port)
	again, err := Listen(p, echoDial(make(chan string, 1)))
	if err != nil {
		t.Fatal(err)
	}
	defer again.Close()
	if again.Addr() != first.Addr() {
		t.Fatalf("Addr() = %s, want the preferred %s", again.Addr(), first.Addr())
	}
	// Taken: another free port.
	other, err := Listen(p, echoDial(make(chan string, 1)))
	if err != nil {
		t.Fatal(err)
	}
	defer other.Close()
	if other.Addr() == again.Addr() {
		t.Fatal("two proxies on one port")
	}
}
