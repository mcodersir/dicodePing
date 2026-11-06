using ServiceLib.Services;
using System.Text.Json.Nodes;
using Xunit;

namespace ServiceLib.Tests;

public class FoxBrowserGrantTests
{
    static string Payload(string nonce = "fixture") => new JsonObject {
        ["kind"] = "grant", ["nonce"] = nonce, ["email"] = "fixture@example.test",
        ["access_token"] = new string('a', 64), ["refresh_token"] = new string('b', 64), ["expires_in"] = 3600
    }.ToJsonString();
    [Fact] public void BrowserGrantUsesExistingCoreStateWithoutSessionOrPassword()
    {
        var before = DateTimeOffset.UtcNow.ToUnixTimeSeconds();
        var state = FoxBrowserProtocol.ParseGrant("https://accounts.firefox.com/", Payload(), "fixture")!;
        Assert.NotNull(state);
        Assert.Equal(new string('a',64), state["access_token"]!.GetValue<string>());
        Assert.InRange(state["expires_at"]!.GetValue<long>(), before+3600, before+3602);
        Assert.False(state.ContainsKey("session_token")); Assert.False(state.ContainsKey("password"));
    }
    [Theory]
    [InlineData("https://accounts.firefox.com.evil.invalid/")]
    [InlineData("http://accounts.firefox.com/")]
    [InlineData("https://accounts.firefox.com:444/")]
    public void RejectsForeignOrigin(string url) => Assert.Null(FoxBrowserProtocol.ParseGrant(url, Payload(), "fixture"));
    [Fact] public void RejectsReplayAndMalformedGrant()
    {
        Assert.Null(FoxBrowserProtocol.ParseGrant("https://accounts.firefox.com", Payload("other"), "fixture"));
        foreach(var (field,value) in new (string,JsonNode?)[] { ("access_token","invalid"), ("refresh_token","bad\nvalue"), ("expires_in",-1), ("expires_in",31536001), ("expires_in","3600"), ("email","bad\n@example.test") })
        {
            var data=JsonNode.Parse(Payload())!.AsObject();data[field]=value;
            Assert.Null(FoxBrowserProtocol.ParseGrant("https://accounts.firefox.com",data.ToJsonString(),"fixture"));
        }
    }
    [Fact] public void PendingSessionAndReadyMessagesRequireTheSameTrustedBrowser()
    {
        var pending = new JsonObject { ["kind"]="pending_session", ["nonce"]="fixture", ["email"]="fixture@example.test", ["session_token"]=new string('a',64) }.ToJsonString();
        Assert.NotNull(FoxBrowserProtocol.ParsePending("https://accounts.firefox.com",pending,"fixture"));
        Assert.Null(FoxBrowserProtocol.ParsePending("https://foreign.invalid",pending,"fixture"));
        Assert.Null(FoxBrowserProtocol.ParsePending("https://accounts.firefox.com",pending,"other"));
        const string ready="{\"kind\":\"bridge_ready\",\"nonce\":\"fixture\"}";
        Assert.True(FoxBrowserProtocol.IsReady("https://accounts.firefox.com",ready,"fixture"));
        Assert.False(FoxBrowserProtocol.IsReady("https://foreign.invalid",ready,"fixture"));
        Assert.False(FoxBrowserProtocol.IsReady("https://accounts.firefox.com",ready,"other"));
    }
    [Fact] public void BrowserErrorsStayBoundToOriginNonceAndKnownCodes()
    {
        const string payload="{\"kind\":\"auth_error\",\"nonce\":\"fixture\",\"code\":\"verification_required\"}";
        Assert.Equal("verification_required",FoxBrowserProtocol.ParseError("https://accounts.firefox.com",payload,"fixture"));
        Assert.Null(FoxBrowserProtocol.ParseError("https://foreign.invalid",payload,"fixture"));
        Assert.Null(FoxBrowserProtocol.ParseError("https://accounts.firefox.com",payload,"other"));
        Assert.Null(FoxBrowserProtocol.ParseError("https://accounts.firefox.com",payload.Replace("verification_required","untrusted error body"),"fixture"));
    }
}
