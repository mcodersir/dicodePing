using Xunit;
namespace ServiceLib.Tests;
public class CustomRoutingProbeTests
{
 [Fact] public void BlockFirstServerlessKeepsItsDnsAndConditionalRoutes() {
  const string content = """{"inbounds":[{"tag":"tun","protocol":"tun"}],"dns":{"servers":["https://1.1.1.1/dns-query"]},"outbounds":[{"tag":"block","protocol":"blackhole"},{"tag":"allowed","protocol":"freedom"}],"routing":{"rules":[{"type":"field","domain":["domain:youtube.com"],"outboundTag":"allowed"}]}}""";
  var before=JsonNode.Parse(content)!;
  var after=JsonNode.Parse(CustomProbeConfiguration.Build(content,ECoreType.Xray,17890))!;
  Assert.Equal(before["routing"]!.ToJsonString(),after["routing"]!.ToJsonString());
  Assert.Equal(before["dns"]!.ToJsonString(),after["dns"]!.ToJsonString());
  Assert.Equal(before["outbounds"]!.ToJsonString(),after["outbounds"]!.ToJsonString());
  Assert.Equal("tun",after["inbounds"]![0]!["tag"]!.ToString());
  Assert.Equal(17890,after["inbounds"]![0]!["port"]!.GetValue<int>());
 }
}
