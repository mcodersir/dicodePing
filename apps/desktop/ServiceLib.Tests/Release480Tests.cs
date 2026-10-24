using ServiceLib.Tests.CoreConfig;
using Xunit;
namespace ServiceLib.Tests;
public class Release480Tests
{
    [Fact]
    public async Task RejectedFoxProbeGetsAnIndependentPortAndLeavesTheActiveEndpointAvailable()
    {
        var config = CoreConfigTestFactory.CreateConfig(); CoreConfigTestFactory.BindAppManagerConfig(config);
        var active = new TcpListener(IPAddress.Loopback, FoxProfiles.LocalPort); active.Start();
        try {
            var node = new ProfileItem { ConfigType = EConfigType.SOCKS, CoreType = ECoreType.sing_box, Address = "127.0.0.1", Port = FoxProfiles.LocalPort };
            node.SetProtocolExtra(new ProtocolExtraItem { FoxAccountId = Guid.NewGuid().ToString("N"), FoxCountry = "REC" });
            var item = new ServerTestItem { Profile = node, ConfigType = EConfigType.SOCKS, Port = FoxProfiles.LocalPort };
            var error = await Assert.ThrowsAsync<FoxException>(() => CoreManager.Instance.LoadCoreConfigSpeedtest(item));
            Assert.Equal("login_required", error.Code); Assert.NotEqual(FoxProfiles.LocalPort, item.Port); Assert.InRange(item.Port, 1, 65535);
            Assert.Equal(FoxProfiles.LocalPort, node.Port);
            using var client = new TcpClient(); await client.ConnectAsync(IPAddress.Loopback, FoxProfiles.LocalPort);
            using var accepted = await active.AcceptTcpClientAsync(); Assert.True(accepted.Connected);
        } finally { active.Stop(); }
    }
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
    public void OrdinaryXrayKeepsNativeTunWhenLegacySettingsAreRetained()
    {
        var config = CoreConfigTestFactory.CreateConfig(); config.TunModeItem.EnableTun = true; config.TunModeItem.EnableLegacyProtect = false;
        CoreConfigTestFactory.BindAppManagerConfig(config);
        var node = CoreConfigTestFactory.CreateVmessNode(ECoreType.Xray);
        var bridge = ConfigHandler.GetPreSocksItem(config, node, ECoreType.Xray);
        Assert.Null(bridge);
        config.TunModeItem.EnableLegacyProtect = true;
        bridge = ConfigHandler.GetPreSocksItem(config, node, ECoreType.Xray);
        Assert.Null(bridge);
        config.TunModeItem.EnableTun = false; Assert.Null(ConfigHandler.GetPreSocksItem(config, node, ECoreType.Xray));
    }
}
