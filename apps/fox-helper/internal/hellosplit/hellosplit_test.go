package hellosplit

import (
	"bytes"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/tls"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/binary"
	"io"
	"math/big"
	"net"
	"sync"
	"testing"
	"time"
)

// clientHello is the ClientHello crypto/tls writes for name.
func clientHello(t *testing.T, name string) []byte {
	t.Helper()
	client, server := net.Pipe()
	defer client.Close()
	defer server.Close()
	go func() {
		_ = tls.Client(client, &tls.Config{ServerName: name, NextProtos: []string{"h2"}}).Handshake()
	}()
	buf := make([]byte, 8192)
	n, err := server.Read(buf)
	if err != nil {
		t.Fatal(err)
	}
	return buf[:n]
}

func TestSegmentsCutTheName(t *testing.T) {
	const name = "p.m1.fastly-masque.net"
	hello := clientHello(t, name)
	start, err := nameOffset(hello)
	if err != nil {
		t.Fatal(err)
	}
	if got := string(hello[start : start+len(name)]); got != name {
		t.Fatalf("the name at the offset is %q", got)
	}
	parts, err := segments(hello, SNI)
	if err != nil {
		t.Fatal(err)
	}
	if len(parts) != 3 || !bytes.Equal(bytes.Join(parts, nil), hello) {
		t.Fatalf("the parts do not make up the hello: %d parts", len(parts))
	}
	for i, part := range parts {
		if bytes.Contains(part, []byte(name)) {
			t.Fatalf("part %d holds the whole name", i)
		}
	}
	parts, err = segments(hello, FirstByte)
	if err != nil {
		t.Fatal(err)
	}
	if len(parts) != 2 || len(parts[0]) != 1 || !bytes.Equal(bytes.Join(parts, nil), hello) {
		t.Fatalf("first-byte parts are wrong: %d", len(parts))
	}
}

func TestNameOffsetRefusesWhatDoesNotParse(t *testing.T) {
	hello := clientHello(t, "example.com")
	for _, cut := range []int{0, 5, 20, 44, 60} {
		if _, err := nameOffset(hello[:cut]); err == nil {
			t.Errorf("a hello cut at %d parsed", cut)
		}
	}
	// Without a server name: an IP address as the name sends none.
	if _, err := nameOffset(clientHello(t, "192.0.2.1")); err == nil {
		t.Error("a hello without a name gave an offset")
	}
}

// recordingConn is the network side of a splitConn: each Write is a segment.
type recordingConn struct {
	net.Conn
	mu     sync.Mutex
	writes [][]byte
}

func (c *recordingConn) Write(p []byte) (int, error) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.writes = append(c.writes, append([]byte(nil), p...))
	return len(p), nil
}

func TestConnSplitsOnlyHellos(t *testing.T) {
	t.Cleanup(func() { Set(Off) })
	Set(SNI)
	rec := &recordingConn{}
	conn := Wrap(rec)
	if _, err := conn.Write([]byte("CONNECT example.com:443 HTTP/1.1\r\n\r\n")); err != nil {
		t.Fatal(err)
	}
	if len(rec.writes) != 1 {
		t.Fatalf("plain text was cut: %d writes", len(rec.writes))
	}
	hello := clientHello(t, "example.com")
	n, err := conn.Write(hello)
	if err != nil || n != len(hello) {
		t.Fatalf("Write = %d, %v; want %d", n, err, len(hello))
	}
	if len(rec.writes) != 4 {
		t.Fatalf("the hello went out in %d writes", len(rec.writes)-1)
	}
	if !bytes.Equal(bytes.Join(rec.writes[1:], nil), hello) {
		t.Fatal("the bytes changed")
	}
}

// Record sends two records in one write: together they carry the hello's
// message, cut inside the name, and the caller is told its own length.
func TestRecordMakesTwoRecords(t *testing.T) {
	t.Cleanup(func() { Set(Off) })
	Set(Record)
	rec := &recordingConn{}
	hello := clientHello(t, "example.com")
	n, err := Wrap(rec).Write(hello)
	if err != nil || n != len(hello) {
		t.Fatalf("Write = %d, %v; want %d", n, err, len(hello))
	}
	if len(rec.writes) != 1 {
		t.Fatalf("the hello went out in %d writes", len(rec.writes))
	}
	out := rec.writes[0]
	first := int(binary.BigEndian.Uint16(out[3:]))
	second := out[5+first:]
	if !bytes.Equal(out[:3], hello[:3]) || !bytes.Equal(second[:3], hello[:3]) {
		t.Fatalf("record headers %x and %x, want %x", out[:3], second[:3], hello[:3])
	}
	if int(binary.BigEndian.Uint16(second[3:])) != len(second)-5 {
		t.Fatal("the second record's length is wrong")
	}
	if message := append(append([]byte(nil), out[5:5+first]...), second[5:]...); !bytes.Equal(message, hello[5:]) {
		t.Fatal("the message changed")
	}
	if !bytes.HasSuffix(out[5:5+first], []byte("e")) || !bytes.HasPrefix(second[5:], []byte("xample.com")) {
		t.Fatal("the cut is not inside the name")
	}
}

// What does not parse goes out whole.
func TestRecordLeavesWhatDoesNotParse(t *testing.T) {
	t.Cleanup(func() { Set(Off) })
	Set(Record)
	hello := clientHello(t, "example.com")
	short := hello[:len(hello)-1]
	rec := &recordingConn{}
	if n, err := Wrap(rec).Write(short); err != nil || n != len(short) {
		t.Fatalf("Write = %d, %v", n, err)
	}
	if len(rec.writes) != 1 || !bytes.Equal(rec.writes[0], short) {
		t.Fatal("a partial record was changed")
	}
}

func TestOffSendsTheHelloWhole(t *testing.T) {
	t.Cleanup(func() { Set(Off) })
	hello := clientHello(t, "example.com")
	for _, mode := range []string{Off, ""} {
		Set(mode)
		rec := &recordingConn{}
		if _, err := Wrap(rec).Write(hello); err != nil {
			t.Fatal(err)
		}
		if len(rec.writes) != 1 {
			t.Fatalf("mode %q: the hello went out in %d writes", mode, len(rec.writes))
		}
	}
}

func TestValid(t *testing.T) {
	for _, mode := range []string{"", Off, SNI, FirstByte, Record} {
		if !Valid(mode) {
			t.Errorf("%q is refused", mode)
		}
	}
	if Valid("auto") {
		t.Error("auto is accepted")
	}
}

// A real handshake over real TCP completes in every way: the server sees
// the same bytes.
func TestHandshakeCompletesEachWay(t *testing.T) {
	t.Cleanup(func() { Set(Off) })
	roots, cert := testCertificate(t, "split.example")
	ln, err := tls.Listen("tcp", "127.0.0.1:0", &tls.Config{Certificates: []tls.Certificate{cert}, NextProtos: []string{"h2"}})
	if err != nil {
		t.Fatal(err)
	}
	defer ln.Close()
	go func() {
		for {
			conn, err := ln.Accept()
			if err != nil {
				return
			}
			go func() {
				defer conn.Close()
				if tc, ok := conn.(*tls.Conn); ok {
					_ = tc.Handshake()
				}
				_, _ = conn.Write([]byte("ok"))
				_, _ = io.Copy(io.Discard, conn)
			}()
		}
	}()
	for _, way := range []string{Off, SNI, FirstByte, Record} {
		Set(way)
		raw, err := net.DialTimeout("tcp", ln.Addr().String(), 5*time.Second)
		if err != nil {
			t.Fatal(err)
		}
		conn := tls.Client(Wrap(raw), &tls.Config{ServerName: "split.example", RootCAs: roots, NextProtos: []string{"h2"}})
		_ = conn.SetDeadline(time.Now().Add(5 * time.Second))
		if err := conn.Handshake(); err != nil {
			t.Fatalf("way %s: %v", way, err)
		}
		buf := make([]byte, 2)
		if _, err := io.ReadFull(conn, buf); err != nil || string(buf) != "ok" {
			t.Fatalf("way %s: read %q, %v", way, buf, err)
		}
		_ = conn.Close()
	}
}

func testCertificate(t *testing.T, name string) (*x509.CertPool, tls.Certificate) {
	t.Helper()
	key, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	template := &x509.Certificate{
		SerialNumber: big.NewInt(1),
		Subject:      pkix.Name{CommonName: name},
		DNSNames:     []string{name},
		NotBefore:    time.Now().Add(-time.Hour),
		NotAfter:     time.Now().Add(time.Hour),
		IsCA:         true,
		KeyUsage:     x509.KeyUsageCertSign | x509.KeyUsageDigitalSignature,
	}
	der, err := x509.CreateCertificate(rand.Reader, template, template, &key.PublicKey, key)
	if err != nil {
		t.Fatal(err)
	}
	parsed, err := x509.ParseCertificate(der)
	if err != nil {
		t.Fatal(err)
	}
	roots := x509.NewCertPool()
	roots.AddCert(parsed)
	return roots, tls.Certificate{Certificate: [][]byte{der}, PrivateKey: key}
}
