package proxy

import (
	"strconv"
	"strings"
	"testing"
	"time"
)

func TestNoticesCountNewestFirstAndBounded(t *testing.T) {
	t.Parallel()

	var nilNotices *Notices
	nilNotices.record(NoticePort, "22", "") // a server without notices records nothing
	if nilNotices.Since(time.Time{}) != nil {
		t.Fatal("nil notices must be empty")
	}

	n := &Notices{}
	n.record(NoticePort, "9898", "a.example")
	n.record(NoticeCommand, "UDP", "")
	for _, host := range []string{"b.example", "c.example", "a.example", "d.example", "d.example"} {
		n.record(NoticePort, "9898", host)
	}
	got := n.Since(time.Time{})
	if len(got) != 2 || got[0].Detail != "9898" || got[0].Count != 6 || got[1].Detail != "UDP" {
		t.Fatalf("notices %+v", got)
	}
	// The latest distinct destinations, newest first.
	if hosts := strings.Join(got[0].Hosts, " "); hosts != "d.example a.example c.example" {
		t.Fatalf("hosts %q", hosts)
	}
	if later := n.Since(time.Now().Add(time.Minute)); len(later) != 0 {
		t.Fatalf("nothing is newer than the future: %+v", later)
	}
	for port := 1; port <= maxNotices+5; port++ {
		n.record(NoticePort, strconv.Itoa(port), "")
	}
	if all := n.Since(time.Time{}); len(all) != maxNotices {
		t.Fatalf("kept %d notices, want %d", len(all), maxNotices)
	}
}
