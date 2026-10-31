using ServiceLib.Services;
using Xunit;
namespace ServiceLib.Tests;
public class Release4992Tests
{
 [Theory]
 [InlineData("https://accounts.firefox.com/",true)]
 [InlineData("http://accounts.firefox.com/",false)]
 [InlineData("https://accounts.firefox.com.evil.test/",false)]
 [InlineData("https://evil.test@accounts.firefox.com/",false)]
 [InlineData("https://accounts.firefox.com:8443/",false)]
 public void BrowserOriginIsPinned(string uri,bool expected)=>Assert.Equal(expected,FoxBrowserProtocol.IsTrusted(uri));
 [Fact] public void BrowserSessionRequiresMatchingNonceAndExactOrigin()
 {
  var json="{\"kind\":\"session\",\"nonce\":\"expected\",\"email\":\"fixture@example.test\",\"session_token\":\""+new string('1',64)+"\"}";
  Assert.NotNull(FoxBrowserProtocol.Parse("https://accounts.firefox.com/",json,"expected"));
  Assert.Null(FoxBrowserProtocol.Parse("https://evil.test/",json,"expected"));
  Assert.Null(FoxBrowserProtocol.Parse("https://accounts.firefox.com/",json,"other"));
  Assert.Null(FoxBrowserProtocol.Parse("https://accounts.firefox.com/",json.Replace(new string('1',64),"guardian.jwt.token"),"expected"));
 }
 [Fact] public void BrowserSessionTokensAreRedactedInReports()
 {
  var safe=DiagnosticArchive.Redact("{\"sessionToken\":\"private-browser-token\",\"authPW\":\"private-password-hash\"}");
  Assert.DoesNotContain("private-browser-token",safe);Assert.DoesNotContain("private-password-hash",safe);
 }
}
