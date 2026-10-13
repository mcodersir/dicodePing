using ServiceLib.Tests.CoreConfig;
using Xunit;
namespace ServiceLib.Tests;
public class Release480Tests
{
    [Fact]
    public void SmallTrafficSamplesAreRecordedWithoutRoundingAwayEverySecond()
    {
        var counter = new ServiceLib.Services.Statistics.TrafficKiBAccumulator(); long up = 0, down = 0;
        for (var i = 0; i < 16; i++) { var sample = counter.Add(64, 128); up += sample.Up; down += sample.Down; }
        Assert.Equal(1, up); Assert.Equal(2, down);
        counter.Add(900, 900); counter.Reset(); Assert.Equal((0L, 0L), counter.Add(124, 124));
    }
    [Fact]
    public void ManagedFoxProbeOwnsItsHelperWhilePlainSocksDoesNot()
    {
        var config = CoreConfigTestFactory.CreateConfig();
        var node = new ProfileItem { ConfigType = EConfigType.SOCKS, CoreType = ECoreType.sing_box, Address = "127.0.0.1", Port = 7854 };
        var item = new ServerTestItem { ConfigType = EConfigType.SOCKS, Profile = node };
        Assert.False(CoreManager.RequiresIsolatedProbe(config, item));
        node.SetProtocolExtra(new ProtocolExtraItem { FoxAccountId = Guid.NewGuid().ToString("N"), FoxCountry = "REC" });
        Assert.True(CoreManager.RequiresIsolatedProbe(config, item));
        var restored = JsonUtils.Deserialize<ProfileItem>(JsonUtils.Serialize(node))!;
        Assert.NotNull(FoxProfiles.Read(restored));
        item.Profile = restored; Assert.True(CoreManager.RequiresIsolatedProbe(config, item));
    }
    [Fact]
    public void WindowsOrdinaryXrayTunUsesBridgeEvenWithLegacySwitchOff()
    {
        var config = CoreConfigTestFactory.CreateConfig(); config.TunModeItem.EnableTun = true; config.TunModeItem.EnableLegacyProtect = false;
        CoreConfigTestFactory.BindAppManagerConfig(config);
        var node = CoreConfigTestFactory.CreateVmessNode(ECoreType.Xray);
        var bridge = ConfigHandler.GetPreSocksItem(config, node, ECoreType.Xray);
        if (OperatingSystem.IsWindows()) { Assert.NotNull(bridge); Assert.Equal(ECoreType.sing_box, bridge.CoreType); }
        else Assert.Null(bridge);
        config.TunModeItem.EnableTun = false; Assert.Null(ConfigHandler.GetPreSocksItem(config, node, ECoreType.Xray));
    }
}
