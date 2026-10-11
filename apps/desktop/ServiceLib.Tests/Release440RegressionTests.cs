using Xunit;

namespace ServiceLib.Tests;

public class Release440RegressionTests
{
    [Theory]
    [InlineData(true, true, true, true)]
    [InlineData(false, true, true, false)]
    [InlineData(true, false, true, false)]
    [InlineData(true, true, false, false)]
    public void StartupOnlyPreparesExistingEnabledDefault(bool autoTest, bool enabled, bool present, bool expected)
    {
        var config = new Config { GuiItem = new GUIItem { AutoTestDefaultSubscription = autoTest } };
        Assert.Equal(expected, DicodePingBootstrap.ShouldPrepare(config, present ? new SubItem { Enabled = enabled } : null));
    }

    [Fact]
    public void SniPresetPreservesCertificateValidationAndExistingUserMask()
    {
        var profile = new ProfileItem { StreamSecurity = "tls", Network = "ws", AllowInsecure = "false", Finalmask = "existing", CipherSuites = "custom" };
        SniBlockPreset.Apply(profile);
        Assert.Equal("unsafe", profile.Fingerprint);
        Assert.Equal("false", profile.AllowInsecure);
        Assert.Equal("existing", profile.Finalmask);
        Assert.Equal("custom", profile.CipherSuites);
        Assert.Equal("http/1.1", profile.Alpn);
        profile.StreamSecurity = "reality"; profile.Fingerprint = "chrome";
        SniBlockPreset.Apply(profile);
        Assert.Equal("chrome", profile.Fingerprint);
    }

    [Theory]
    [InlineData(ECoreType.Xray)]
    [InlineData(ECoreType.sing_box)]
    public void EntryHopWrapsTerminalOfChainAndNeverReplacesExistingDetour(ECoreType core)
    {
        var config = new Config { EntryHopItem = new EntryHopItem { Enabled = true, Port = 61080 } };
        var context = new CoreConfigContext { Node = new ProfileItem { ConfigType = EConfigType.VLESS }, AppConfig = config, RunCoreType = core, UseEntryHop = true };
        var source = core == ECoreType.Xray
            ? """{"outbounds":[{"tag":"proxy","streamSettings":{"sockopt":{"dialerProxy":"proxy-first"}}},{"tag":"proxy-first","streamSettings":{}},{"tag":"direct","protocol":"freedom"}]}"""
            : """{"outbounds":[{"tag":"proxy","detour":"proxy-first"},{"tag":"proxy-first","type":"vless"},{"tag":"direct","type":"direct"}]}""";
        var root = JsonNode.Parse(EntryHopConfiguration.Apply(source, context))!;
        Assert.Equal("proxy-first", core == ECoreType.Xray ? root["outbounds"]![0]!["streamSettings"]!["sockopt"]!["dialerProxy"]!.ToString() : root["outbounds"]![0]!["detour"]!.ToString());
        Assert.Equal(EntryHopConfiguration.Tag, core == ECoreType.Xray ? root["outbounds"]![1]!["streamSettings"]!["sockopt"]!["dialerProxy"]!.ToString() : root["outbounds"]![1]!["detour"]!.ToString());
        Assert.Null(root["outbounds"]![2]!["detour"]);
        Assert.Equal(4, root["outbounds"]!.AsArray().Count);
        Assert.Equal(source, EntryHopConfiguration.Apply(source, context with { UseEntryHop = false }));
        Assert.Throws<InvalidOperationException>(() => EntryHopConfiguration.Apply("{\"outbounds\":[]}", context));
    }

    [Theory]
    [InlineData(ECoreType.Xray)]
    [InlineData(ECoreType.sing_box)]
    public void CustomProbeKeepsOutboundChainAndUsesOnlyIsolatedSocksListener(ECoreType core)
    {
        var content = core == ECoreType.Xray
            ? """{"api":{"tag":"api"},"inbounds":[{"protocol":"tun","port":1234}],"outbounds":[{"tag":"proxy","protocol":"vless","streamSettings":{"sockopt":{"dialerProxy":"first"}}},{"tag":"first","protocol":"socks"}],"routing":{"rules":[]}}"""
            : """{"inbounds":[{"type":"tun"}],"outbounds":[{"tag":"proxy","type":"vless","detour":"first"},{"tag":"first","type":"socks"}],"route":{"rules":[]}}""";
        var parsed = JsonNode.Parse(CustomProbeConfiguration.Build(content, core, 16080))!;
        Assert.Null(parsed["api"]);
        Assert.Single(parsed["inbounds"]!.AsArray());
        Assert.Equal("socks", parsed["inbounds"]![0]![core == ECoreType.Xray ? "protocol" : "type"]!.ToString());
        Assert.Equal(JsonNode.Parse(content)!["outbounds"]!.ToJsonString(), parsed["outbounds"]!.ToJsonString());
        Assert.Equal(1, parsed[core == ECoreType.Xray ? "routing" : "route"]!["rules"]!.AsArray().Count);
        Assert.Throws<NotSupportedException>(() => CustomProbeConfiguration.Build(content, ECoreType.mihomo, 16080));
    }

    [Fact]
    public void EntryHopScopeDoesNotCaptureUnrelatedProfiles()
    {
        var item = new EntryHopItem { Enabled = true, SubscriptionId = "default" };
        Assert.True(item.Applies(new ProfileItem { Subid = "default" }));
        Assert.False(item.Applies(new ProfileItem { Subid = "other" }));
        item.ProfileId = "one";
        Assert.True(item.Applies(new ProfileItem { IndexId = "one", Subid = "other" }));
        Assert.False(item.Applies(new ProfileItem { IndexId = "two", Subid = "default" }));
    }
}
