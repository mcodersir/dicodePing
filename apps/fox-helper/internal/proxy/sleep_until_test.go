package proxy

import (
	"testing"
	"time"
)

func TestSleepUntilFollowsTheWallClock(t *testing.T) {
	c := &Controller{done: make(chan struct{})}
	start := time.Now()
	if !c.sleepUntil(time.Now().Round(0).Add(-time.Minute)) || time.Since(start) > time.Second {
		t.Fatal("a time already past returns at once")
	}
	start = time.Now()
	if !c.sleepUntil(time.Now().Round(0).Add(200 * time.Millisecond)) {
		t.Fatal("not closed")
	}
	if waited := time.Since(start); waited < 150*time.Millisecond || waited > 2*time.Second {
		t.Fatalf("waited %s for 200ms", waited)
	}
	close(c.done)
	if c.sleepUntil(time.Now().Round(0).Add(time.Hour)) {
		t.Fatal("a closed controller stops waiting")
	}
}
