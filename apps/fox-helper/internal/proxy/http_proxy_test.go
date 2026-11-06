package proxy

import (
	"bufio"
	"encoding/base64"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"testing"
	"time"
)

// backendOpener opens every tunnel to one local server.
type backendOpener string

func (b backendOpener) OpenTunnel(string) (net.Conn, error) { return net.Dial("tcp", string(b)) }

func startMixedProxy(t *testing.T, server *SOCKSServer) string {
	t.Helper()
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = ln.Close() })
	go ServeSOCKS(ln, server)
	return ln.Addr().String()
}

// rawRequest sends text to the proxy and returns the response head and
// the connection, positioned after the head.
func rawRequest(t *testing.T, proxyAddr, text string) (*http.Response, *bufio.Reader, net.Conn) {
	t.Helper()
	conn, err := net.Dial("tcp", proxyAddr)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = conn.Close() })
	_ = conn.SetDeadline(time.Now().Add(5 * time.Second))
	if _, err := io.WriteString(conn, text); err != nil {
		t.Fatal(err)
	}
	reader := bufio.NewReader(conn)
	resp, err := http.ReadResponse(reader, nil)
	if err != nil {
		t.Fatal(err)
	}
	return resp, reader, conn
}

func TestHTTPProxyConnectTunnel(t *testing.T) {
	echo, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer echo.Close()
	go func() {
		for {
			c, err := echo.Accept()
			if err != nil {
				return
			}
			go func() { _, _ = io.Copy(c, c); _ = c.Close() }()
		}
	}()
	proxyAddr := startMixedProxy(t, &SOCKSServer{upstream: backendOpener(echo.Addr().String())})

	// Bytes sent right behind the CONNECT request must not be lost.
	resp, reader, conn := rawRequest(t, proxyAddr, "CONNECT example.com:443 HTTP/1.1\r\nHost: example.com:443\r\n\r\nearly")
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("CONNECT: %s", resp.Status)
	}
	if _, err := io.WriteString(conn, " data"); err != nil {
		t.Fatal(err)
	}
	got := make([]byte, len("early data"))
	if _, err := io.ReadFull(reader, got); err != nil || string(got) != "early data" {
		t.Fatalf("echo %q %v", got, err)
	}
}

func TestHTTPProxyForwardsPlainRequests(t *testing.T) {
	var seen *http.Request
	site := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		seen = r
		_, _ = io.WriteString(w, "hello from the site")
	}))
	defer site.Close()
	creds := SOCKSCredentials("user", "secret")
	proxyAddr := startMixedProxy(t, &SOCKSServer{upstream: backendOpener(site.Listener.Addr().String()), Auth: creds})

	client := &http.Client{Timeout: 5 * time.Second, Transport: &http.Transport{Proxy: http.ProxyURL(&url.URL{Scheme: "http", Host: proxyAddr})}}
	resp, err := client.Get("http://site.example/page?x=1")
	if err != nil {
		t.Fatal(err)
	}
	resp.Body.Close()
	if resp.StatusCode != http.StatusProxyAuthRequired || !strings.Contains(resp.Header.Get("Proxy-Authenticate"), "Basic") {
		t.Fatalf("without a login: %s %v", resp.Status, resp.Header)
	}

	client.Transport = &http.Transport{Proxy: http.ProxyURL(&url.URL{Scheme: "http", User: url.UserPassword("user", "secret"), Host: proxyAddr})}
	resp, err = client.Get("http://site.example/page?x=1")
	if err != nil {
		t.Fatal(err)
	}
	body, _ := io.ReadAll(resp.Body)
	resp.Body.Close()
	if resp.StatusCode != http.StatusOK || string(body) != "hello from the site" {
		t.Fatalf("got %s %q", resp.Status, body)
	}
	if seen == nil || seen.RequestURI != "/page?x=1" || seen.Host != "site.example" || seen.Header.Get("Proxy-Authorization") != "" {
		t.Fatalf("the site saw %+v", seen)
	}
}

// A port Mozilla's proxy refuses is explained to HTTP clients too.
func TestHTTPProxyExplainsRefusedPort(t *testing.T) {
	notices := &Notices{}
	proxyAddr := startMixedProxy(t, &SOCKSServer{upstream: refusingOpener{}, Notices: notices})
	resp, reader, _ := rawRequest(t, proxyAddr, "CONNECT 203.0.113.5:9898 HTTP/1.1\r\nHost: 203.0.113.5:9898\r\n\r\n")
	body, _ := io.ReadAll(io.LimitReader(reader, 512))
	if resp.StatusCode != http.StatusForbidden || !strings.Contains(string(body), "port 9898") {
		t.Fatalf("got %s %q", resp.Status, body)
	}
	if got := notices.Since(time.Time{}); len(got) != 1 || got[0].Detail != "9898" {
		t.Fatalf("notices %+v", got)
	}
}

func TestBasicCredentials(t *testing.T) {
	creds := SOCKSCredentials("user", "p:ss")
	encode := func(s string) string { return "Basic " + base64.StdEncoding.EncodeToString([]byte(s)) }
	if !creds.matchBasic(encode("user:p:ss")) || creds.matchBasic(encode("user:wrong")) || creds.matchBasic("Bearer x") || creds.matchBasic(encode("user")) {
		t.Fatal("basic credentials")
	}
}
