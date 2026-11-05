using System.Text.Json.Nodes;
using ServiceLib.Services;
using ServiceLib.Services.CoreConfig;
using ServiceLib.Tests.CoreConfig;
using ServiceLib.Enums;
using Xunit;
namespace ServiceLib.Tests;
public class Release4993Tests
{
 [Theory]
 [InlineData("[\"fakedns\"]")]
 [InlineData("[{\"address\":\"fakedns\"}]")]
 public void CustomFakeDnsMustRewriteSyntheticDestination(string servers)
 {
  var root=JsonNode.Parse("{\"dns\":{\"servers\":"+servers+"},\"inbounds\":[{\"protocol\":\"tun\",\"sniffing\":{\"enabled\":false,\"routeOnly\":true,\"destOverride\":[\"tls\"]}}]}")!.AsObject();
  FakeDnsPolicy.Apply(root);var sniff=root["inbounds"]![0]!["sniffing"]!;
  Assert.True(sniff["enabled"]!.GetValue<bool>());Assert.False(sniff["routeOnly"]!.GetValue<bool>());
  Assert.Contains(sniff["destOverride"]!.AsArray(),x=>x!.ToString()=="fakedns");
  FakeDnsPolicy.Apply(root);Assert.Equal(2,sniff["destOverride"]!.AsArray().Count);
 }
 [Fact] public void NativeTunFakeDnsOverridesUserRouteOnly()
 {
  var config=CoreConfigTestFactory.CreateConfigWithTun(ECoreType.Xray,false);config.SimpleDNSItem.FakeIP=true;
  config.Inbound[0].RouteOnly=true;config.Inbound[0].SniffingEnabled=false;CoreConfigTestFactory.BindAppManagerConfig(config);
  var node=CoreConfigTestFactory.CreateVmessNode(ECoreType.Xray);
  var context=CoreConfigTestFactory.CreateContext(config,node,ECoreType.Xray);
  var r=new CoreConfigV2rayService(context).GenerateClientConfigContent();Assert.True(r.Success,r.Msg);
  var root=JsonNode.Parse(r.Data!.ToString()!)!;
  foreach(var inbound in root["inbounds"]!.AsArray()){
   Assert.True(inbound!["sniffing"]!["enabled"]!.GetValue<bool>());Assert.False(inbound["sniffing"]!["routeOnly"]!.GetValue<bool>());
  }
 }
}
