using Xunit;
namespace ServiceLib.Tests;
public class FakeDnsPolicyTests
{
 [Fact] public void FakeDnsAddressesAreRecoveredOnTunAndSocksBeforeDomainRules() {
  var root=JsonNode.Parse("""{"dns":{"servers":[{"address":"fakedns"}]},"inbounds":[{"protocol":"tun"},{"protocol":"mixed","sniffing":{"enabled":false,"destOverride":["tls"]}}]}""")!.AsObject();
  CustomFakeDnsPolicy.Apply(root);
  foreach(var inbound in root["inbounds"]!.AsArray()) {
   Assert.True(inbound!["sniffing"]!["enabled"]!.GetValue<bool>());
   Assert.False(inbound["sniffing"]!["routeOnly"]!.GetValue<bool>());
   Assert.Contains(inbound["sniffing"]!["destOverride"]!.AsArray(), x=>x!.ToString()=="fakedns");
  }
 }
 [Fact] public void OrdinaryConfigsKeepTheirSniffingPreference() {
  var root=JsonNode.Parse("""{"inbounds":[{"protocol":"mixed","sniffing":{"enabled":false}}]}""")!.AsObject();
  CustomFakeDnsPolicy.Apply(root);Assert.False(root["inbounds"]![0]!["sniffing"]!["enabled"]!.GetValue<bool>());
 }
 [Fact] public void PersianResetDateIncludesGregorianDate() {Assert.Equal("1405/01/01 · 2026-03-21",FoxDates.Format(new DateTimeOffset(2026,3,21,12,0,0,TimeSpan.Zero)));}
 [Fact] public void CountrySnapshotWorksBeforeAnyNetworkRequest() {Assert.Contains("US",FoxLocationCache.Read());Assert.Contains("JP",FoxLocationCache.Read());}
}
