package proxy

import (
	"sort"
	"sync"
	"time"
)

// Notice kinds.
const (
	// NoticePort is a CONNECT to a port Mozilla's proxy refuses; Detail is
	// the port.
	NoticePort = "port"
	// NoticeCommand is a SOCKS command other than CONNECT, such as UDP
	// ASSOCIATE; Detail names it.
	NoticeCommand = "command"
	// NoticeLoop is this program's own connections coming back to its
	// proxy as a client's (loopWatch); Detail is empty.
	NoticeLoop = "loop"
)

// maxNotices bounds the distinct notices kept; maxNoticeHosts the
// destinations kept per notice.
const (
	maxNotices     = 20
	maxNoticeHosts = 3
)

// Notice is a kind of request this proxy cannot serve because of a limit
// of Mozilla's proxy or of this program, so the dashboard can explain it.
// Hosts are the latest distinct destinations (names or addresses), newest
// first; they stay in memory for the dashboard and never reach the log
// unless logging is verbose.
type Notice struct {
	Kind   string    `json:"kind"`
	Detail string    `json:"detail"`
	Hosts  []string  `json:"hosts,omitempty"`
	Count  int       `json:"count"`
	Last   time.Time `json:"last"`
	// seq orders notices: the clock can give two at once the same time.
	seq uint64
}

// Notices collects notices, one entry per kind and detail. The zero value
// is ready; a nil *Notices records nothing.
type Notices struct {
	mu      sync.Mutex
	entries map[string]*Notice
	seq     uint64
}

// record notes one refused request; host is its destination, or empty.
func (n *Notices) record(kind, detail, host string) {
	if n == nil {
		return
	}
	n.mu.Lock()
	defer n.mu.Unlock()
	if n.entries == nil {
		n.entries = make(map[string]*Notice)
	}
	key := kind + "\x00" + detail
	entry, ok := n.entries[key]
	if !ok {
		if len(n.entries) >= maxNotices {
			n.dropOldestLocked()
		}
		entry = &Notice{Kind: kind, Detail: detail}
		n.entries[key] = entry
	}
	n.seq++
	entry.Count++
	entry.Last, entry.seq = time.Now(), n.seq
	if host != "" {
		hosts := []string{host}
		for _, h := range entry.Hosts {
			if h != host && len(hosts) < maxNoticeHosts {
				hosts = append(hosts, h)
			}
		}
		entry.Hosts = hosts
	}
}

func (n *Notices) dropOldestLocked() {
	var oldestKey string
	var oldest uint64
	for key, entry := range n.entries {
		if oldestKey == "" || entry.seq < oldest {
			oldestKey, oldest = key, entry.seq
		}
	}
	delete(n.entries, oldestKey)
}

// Since returns the notices last seen after t, newest first.
func (n *Notices) Since(t time.Time) []Notice {
	if n == nil {
		return nil
	}
	n.mu.Lock()
	defer n.mu.Unlock()
	var out []Notice
	for _, entry := range n.entries {
		if entry.Last.After(t) {
			copied := *entry
			copied.Hosts = append([]string(nil), entry.Hosts...)
			out = append(out, copied)
		}
	}
	sort.Slice(out, func(i, j int) bool { return out[i].seq > out[j].seq })
	return out
}
