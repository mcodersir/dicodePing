package proxy

import (
	"context"
	"errors"
	"io"
	"strings"
	"testing"
	"time"
)

func TestTunnelWriteBufferRoundTripsAcrossWraparound(t *testing.T) {
	t.Parallel()

	b := newTunnelWriteBuffer(8)
	payload := []byte("0123456789abcdefghij")

	done := make(chan error, 1)
	go func() {
		_, err := b.Write(payload)
		done <- err
		_ = b.Close()
	}()

	got := make([]byte, 0, len(payload))
	buf := make([]byte, 5)
	for len(got) < len(payload) {
		n, err := b.Read(buf)
		got = append(got, buf[:n]...)
		if err != nil {
			t.Fatalf("Read returned error after %d bytes: %v", len(got), err)
		}
	}
	if string(got) != string(payload) {
		t.Fatalf("expected %q, got %q", payload, got)
	}
	if err := <-done; err != nil {
		t.Fatalf("Write returned error: %v", err)
	}
}

func TestTunnelWriteBufferWriteDoesNotBlockUntilFull(t *testing.T) {
	t.Parallel()

	b := newTunnelWriteBuffer(16)
	done := make(chan struct{})
	go func() {
		defer close(done)
		if _, err := b.Write([]byte("0123456789")); err != nil {
			t.Errorf("Write returned error: %v", err)
		}
	}()

	select {
	case <-done:
	case <-time.After(2 * time.Second):
		t.Fatal("Write blocked even though the buffer had room")
	}
}

func TestTunnelWriteBufferCloseKeepsBufferedDataReadable(t *testing.T) {
	t.Parallel()

	b := newTunnelWriteBuffer(16)
	if _, err := b.Write([]byte("tail")); err != nil {
		t.Fatalf("Write returned error: %v", err)
	}
	if err := b.Close(); err != nil {
		t.Fatalf("Close returned error: %v", err)
	}

	buf := make([]byte, 8)
	n, err := b.Read(buf)
	if err != nil {
		t.Fatalf("Read returned error: %v", err)
	}
	if string(buf[:n]) != "tail" {
		t.Fatalf("expected buffered data to survive Close, got %q", buf[:n])
	}
	if _, err := b.Read(buf); !errors.Is(err, io.EOF) {
		t.Fatalf("expected EOF once drained, got %v", err)
	}
}

func TestTunnelWriteBufferFailReadUnblocksBlockedWriter(t *testing.T) {
	t.Parallel()

	b := newTunnelWriteBuffer(4)
	errCh := make(chan error, 1)
	go func() {
		_, err := b.Write([]byte("far more than four bytes"))
		errCh <- err
	}()

	// Let the writer fill the buffer and block on notFull.
	time.Sleep(50 * time.Millisecond)
	b.failRead(io.ErrClosedPipe)

	select {
	case err := <-errCh:
		if !errors.Is(err, io.ErrClosedPipe) {
			t.Fatalf("expected io.ErrClosedPipe, got %v", err)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("blocked writer was not released by failRead")
	}
}

func TestTunnelConnCloseWriteClosesRequestBody(t *testing.T) {
	t.Parallel()

	reqBody := newTunnelWriteBuffer(defaultTunnelWriteBufSize)
	conn := &tunnelConn{
		reader:  io.NopCloser(strings.NewReader("")),
		writer:  reqBody,
		reqBody: reqBody,
		name:    "test-tunnel",
	}

	if err := conn.CloseWrite(); err != nil {
		t.Fatalf("CloseWrite returned error: %v", err)
	}

	buf := make([]byte, 1)
	if _, err := reqBody.Read(buf); !errors.Is(err, io.EOF) {
		t.Fatalf("expected request body EOF after CloseWrite, got %v", err)
	}

	if err := conn.Close(); err != nil {
		t.Fatalf("Close returned error: %v", err)
	}
}

func TestTunnelConnCloseCancelsRequestContext(t *testing.T) {
	t.Parallel()

	ctx, cancel := context.WithCancel(context.Background())
	conn := &tunnelConn{
		reader: io.NopCloser(strings.NewReader("")),
		writer: newTunnelWriteBuffer(defaultTunnelWriteBufSize),
		cancel: cancel,
		name:   "test-tunnel",
	}

	if err := conn.Close(); err != nil {
		t.Fatalf("Close returned error: %v", err)
	}
	select {
	case <-ctx.Done():
	case <-time.After(time.Second):
		t.Fatal("expected Close to cancel request context")
	}
}

func TestTunnelConnDeadlineUnsupported(t *testing.T) {
	t.Parallel()

	conn := &tunnelConn{}
	if !errors.Is(conn.SetDeadline(time.Now()), errTunnelDeadline) {
		t.Fatal("expected SetDeadline to report unsupported tunnel deadline")
	}
	if !errors.Is(conn.SetReadDeadline(time.Now()), errTunnelDeadline) {
		t.Fatal("expected SetReadDeadline to report unsupported tunnel deadline")
	}
	if !errors.Is(conn.SetWriteDeadline(time.Now()), errTunnelDeadline) {
		t.Fatal("expected SetWriteDeadline to report unsupported tunnel deadline")
	}
}
