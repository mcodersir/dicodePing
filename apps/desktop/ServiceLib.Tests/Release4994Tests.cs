using System.Text.Json.Nodes;
using ServiceLib.Enums;
using ServiceLib.Handler;
using Xunit;

namespace ServiceLib.Tests;

public class Release4994Tests
{
    [Fact]
    public void ServerlessProbeUsesItsOriginalRoutingAndDns()
    {
        const string raw = """
        {"remarks":"Serverless-v58-oob","dns":{"servers":["fakedns"]},
         "inbounds":[{"tag":"mixed-in","protocol":"mixed","port":10808,"sniffing":{"enabled":true,"destOverride":["fakedns","tls"]}}],
         "outbounds":[{"tag":"block","protocol":"block"},{"tag":"tcp-oob","protocol":"direct"}],
         "routing":{"rules":[{"inboundTag":["mixed-in"],"outboundTag":"tcp-oob","network":"tcp"}]}}
        """;
        var source = JsonNode.Parse(raw)!;
        var probe = JsonNode.Parse(CustomProbeConfiguration.Build(raw, ECoreType.Xray, 22101))!;
        Assert.True(JsonNode.DeepEquals(source["dns"], probe["dns"]));
        Assert.True(JsonNode.DeepEquals(source["routing"], probe["routing"]));
        Assert.True(JsonNode.DeepEquals(source["outbounds"], probe["outbounds"]));
        Assert.Equal("mixed-in", probe["inbounds"]![0]!["tag"]!.GetValue<string>());
        Assert.Equal(22101, probe["inbounds"]![0]!["port"]!.GetValue<int>());
        Assert.False(probe["inbounds"]![0]!["sniffing"]!["routeOnly"]!.GetValue<bool>());
    }
}
