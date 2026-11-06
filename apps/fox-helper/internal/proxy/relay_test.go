package proxy

import (
	"errors"
	"sync/atomic"
	"testing"
	"time"
)

func TestProxyBidirectionalClosesBothSidesOnCopyError(t *testing.T) {
	t.Parallel()

	client := newControlledNetConn(errors.New("client read failed"))
	upstream := newControlledNetConn(nil)
	done := make(chan struct{})
	go func() {
		proxyBidirectional(client, upstream, 0)
		close(done)
	}()

	select {
	case <-done:
	case <-time.After(time.Second):
		t.Fatal("proxyBidirectional did not close the blocked peer after copy error")
	}
	select {
	case <-upstream.closed:
	default:
		t.Fatal("expected upstream connection to be closed")
	}
}

func TestTunnelWrappersForwardHalfCloseAndReleaseOnClose(t *testing.T) {
	t.Parallel()

	tests := []struct {
		name string
		conn func(*fakeHalfCloseConn, *atomic.Int32) halfCloseTestConn
	}{
		{
			name: "pooled",
			conn: func(underlying *fakeHalfCloseConn, releaseCount *atomic.Int32) halfCloseTestConn {
				return &pooledTunnelConn{
					Conn: underlying,
					release: func() {
						releaseCount.Add(1)
					},
				}
			},
		},
		{
			name: "managed",
			conn: func(underlying *fakeHalfCloseConn, releaseCount *atomic.Int32) halfCloseTestConn {
				return &managedTunnelConn{
					Conn: underlying,
					release: func() {
						releaseCount.Add(1)
					},
				}
			},
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			t.Parallel()

			underlying := &fakeHalfCloseConn{}
			var releaseCount atomic.Int32
			conn := tc.conn(underlying, &releaseCount)

			assertHalfCloseForwarding(t, conn, underlying, &releaseCount)
		})
	}
}

func assertHalfCloseForwarding(t *testing.T, conn halfCloseTestConn, underlying *fakeHalfCloseConn, releaseCount *atomic.Int32) {
	t.Helper()

	if err := conn.CloseWrite(); err != nil {
		t.Fatalf("CloseWrite returned error: %v", err)
	}
	if got := underlying.closeWriteCount.Load(); got != 1 {
		t.Fatalf("expected underlying CloseWrite once, got %d", got)
	}

	if err := conn.CloseRead(); err != nil {
		t.Fatalf("CloseRead returned error: %v", err)
	}
	if got := underlying.closeReadCount.Load(); got != 1 {
		t.Fatalf("expected underlying CloseRead once, got %d", got)
	}

	if err := conn.Close(); err != nil {
		t.Fatalf("Close returned error: %v", err)
	}
	if err := conn.Close(); err != nil {
		t.Fatalf("second Close returned error: %v", err)
	}
	if got := releaseCount.Load(); got != 1 {
		t.Fatalf("expected pooled session release once, got %d", got)
	}
}
