package proxy

import (
	"io"
	"net"
	"testing"
	"time"

	"golang.org/x/net/http2"
)

// The server hears of the tunnels' small window in the connection's first
// settings: more would have a download delay every new connection.
func TestUpstreamAnnouncesItsStreamWindow(t *testing.T) {
	transport, err := newUpstreamH2Transport()
	if err != nil {
		t.Fatal(err)
	}
	client, server := net.Pipe()
	defer client.Close()
	defer server.Close()
	_ = server.SetDeadline(time.Now().Add(5 * time.Second))
	done := make(chan error, 1)
	go func() {
		_, err := transport.NewClientConn(client)
		done <- err
	}()
	preface := make([]byte, len(http2.ClientPreface))
	if _, err := io.ReadFull(server, preface); err != nil {
		t.Fatal(err)
	}
	frame, err := http2.NewFramer(nil, server).ReadFrame()
	if err != nil {
		t.Fatal(err)
	}
	settings, ok := frame.(*http2.SettingsFrame)
	if !ok {
		t.Fatalf("first frame: %T", frame)
	}
	window, ok := settings.Value(http2.SettingInitialWindowSize)
	if !ok || window != upstreamStreamWindow {
		t.Fatalf("initial window %d (%t), want %d", window, ok, upstreamStreamWindow)
	}
	_ = client.Close()
	<-done
}
