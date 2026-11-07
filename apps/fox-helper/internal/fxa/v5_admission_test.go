package fxa

import (
    "context"
    "io"
    "net/http"
    "strings"
    "encoding/json"
    "testing"
    "time"
    "dicodeping/fox/internal/controlplane"
)

// Credential-free admission check: an invalid grant must reach FxA's JSON
// validation, rather than an empty edge 406. This never accesses a real account.
func TestV5LiveOAuthAdmission(t *testing.T) {
    for _, endpoint := range []string{"https://api.accounts.firefox.com/v1/oauth/token", "https://oauth.accounts.firefox.com/v1/token"} {
        ctx,cancel:=context.WithTimeout(context.Background(),45*time.Second)
        body,_:=json.Marshal(map[string]string{"grant_type":"refresh_token","client_id":firefoxClientID,"refresh_token":strings.Repeat("invalid-test-",5)})
        req,err:=newOAuthJSONRequest(ctx,endpoint,body)
        if err!=nil {cancel();t.Fatal(err)}
        response,err:=controlplane.Do(req)
        if err!=nil {cancel();t.Fatal(err)}
        raw,_:=io.ReadAll(io.LimitReader(response.Body,8192));response.Body.Close();cancel()
        var origin map[string]any
        if (response.StatusCode!=http.StatusBadRequest && response.StatusCode!=http.StatusUnauthorized) || json.Unmarshal(raw,&origin)!=nil || len(origin)==0 {
            t.Fatalf("FxA admission failed host=%s status=%d protocol=%s",req.URL.Host,response.StatusCode,response.Proto)
        }
        t.Logf("PASS origin validation reached host=%s status=%d protocol=%s; no account credentials used",req.URL.Host,response.StatusCode,response.Proto)
    }
}
