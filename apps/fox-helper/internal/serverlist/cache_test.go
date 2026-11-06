package serverlist

import (
	"path/filepath"
	"testing"
)

// The saved list keeps what Filter and the lock need, and an empty or
// missing file is no list.
func TestServerListCache(t *testing.T) {
	path := filepath.Join(t.TempDir(), "servers.json")
	if _, _, err := LoadCache(path); err == nil {
		t.Fatal("a missing file is no list")
	}
	want := []Country{{Name: "Netherlands", Code: "NL", Locked: true, FilterExpression: "env.version|versionCompare('140') >= 0",
		Cities: []City{{Name: "Amsterdam", Code: "ams", Servers: []Server{{Hostname: "nl.example", Port: 443}}}}}}
	if err := SaveCache(path, want); err != nil {
		t.Fatal(err)
	}
	got, savedAt, err := LoadCache(path)
	if err != nil || savedAt.IsZero() {
		t.Fatalf("%v %v", savedAt, err)
	}
	if len(got) != 1 || !got[0].Locked || got[0].FilterExpression != want[0].FilterExpression || got[0].Cities[0].Servers[0].Hostname != "nl.example" {
		t.Fatalf("got %+v", got)
	}
	if err := SaveCache(path, nil); err != nil {
		t.Fatal(err)
	}
	if _, _, err := LoadCache(path); err == nil {
		t.Fatal("an empty list is no list")
	}
}
