package routing

import (
	"context"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// rewriteTo sends every request to srv: the list URL never reaches GitHub.
type rewriteTo struct{ srv *httptest.Server }

func (r rewriteTo) RoundTrip(req *http.Request) (*http.Response, error) {
	u := *req.URL
	u.Scheme, u.Host = "http", strings.TrimPrefix(r.srv.URL, "http://")
	out := req.Clone(req.Context())
	out.URL, out.Host = &u, u.Host
	return http.DefaultTransport.RoundTrip(out)
}

func TestAppListDownloadKeepsPackageNames(t *testing.T) {
	var asked string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		asked = r.URL.Path
		_, _ = w.Write([]byte("cab.snapp.passenger\n# a comment\n\ncom.digikala\nnot a package\n"))
	}))
	defer srv.Close()
	dir := t.TempDir()
	if !AppListDue(dir, "ir", time.Hour) {
		t.Fatal("a missing list is due")
	}
	client := &http.Client{Transport: rewriteTo{srv}}
	if err := DownloadAppList(context.Background(), client, dir, "ir"); err != nil {
		t.Fatal(err)
	}
	if asked != "/hiddify/Android-GFW-Apps/master/direct_ir" {
		t.Fatalf("asked for %q", asked)
	}
	got := ReadAppList(dir, "ir")
	if strings.Join(got, ",") != "cab.snapp.passenger,com.digikala" {
		t.Fatalf("apps %v", got)
	}
	if AppListDue(dir, "ir", time.Hour) {
		t.Fatal("a fresh list is not due")
	}
}

func TestAppListRefusesAPageWithoutPackages(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte("<html>rate limited</html>"))
	}))
	defer srv.Close()
	dir := t.TempDir()
	if err := DownloadAppList(context.Background(), &http.Client{Transport: rewriteTo{srv}}, dir, "ir"); err == nil {
		t.Fatal("a page without package names must not replace the list")
	}
	if _, err := os.Stat(filepath.Join(dir, AppListFile("ir"))); err == nil {
		t.Fatal("nothing must be written")
	}
}

func TestRegionsWithoutAppList(t *testing.T) {
	if HasAppList("tr") || AppListDue(t.TempDir(), "tr", time.Hour) || ReadAppList(t.TempDir(), "tr") != nil {
		t.Fatal("tr has no app list")
	}
}
