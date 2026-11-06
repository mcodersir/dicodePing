package logx

import (
	"sync"
	"time"
)

// logBufferSize is how many recent log entries the dashboard can show.
const logBufferSize = 2000

// Entry is one log line as served to the dashboard. Messages follow the
// same redaction rules as stderr; they never contain tokens.
type Entry struct {
	ID      uint64    `json:"id"`
	Time    time.Time `json:"time"`
	Level   string    `json:"level"`
	Message string    `json:"message"`
}

// Hub keeps recent log entries in a ring buffer and fans new entries out
// to live subscribers (the dashboard's event stream).
type Hub struct {
	mu          sync.Mutex
	entries     []Entry
	next        uint64
	subscribers map[chan Entry]struct{}
}

// Logs receives every logEvent.
var Logs = newLogHub()

func newLogHub() *Hub {
	return &Hub{subscribers: make(map[chan Entry]struct{})}
}

func (h *Hub) add(t time.Time, level, message string) {
	h.mu.Lock()
	defer h.mu.Unlock()
	h.next++
	entry := Entry{ID: h.next, Time: t, Level: level, Message: message}
	if len(h.entries) == logBufferSize {
		copy(h.entries, h.entries[1:])
		h.entries[len(h.entries)-1] = entry
	} else {
		h.entries = append(h.entries, entry)
	}
	for ch := range h.subscribers {
		select {
		case ch <- entry:
		default:
			// A slow subscriber misses entries rather than blocking logging;
			// it can reload the buffer.
		}
	}
}

// Since returns buffered entries with an id above after.
func (h *Hub) Since(after uint64) []Entry {
	h.mu.Lock()
	defer h.mu.Unlock()
	out := make([]Entry, 0, len(h.entries))
	for _, entry := range h.entries {
		if entry.ID > after {
			out = append(out, entry)
		}
	}
	return out
}

// Subscribe returns a channel of new entries and a function that ends the
// subscription.
func (h *Hub) Subscribe() (<-chan Entry, func()) {
	ch := make(chan Entry, 256)
	h.mu.Lock()
	h.subscribers[ch] = struct{}{}
	h.mu.Unlock()
	return ch, func() {
		h.mu.Lock()
		delete(h.subscribers, ch)
		h.mu.Unlock()
	}
}
