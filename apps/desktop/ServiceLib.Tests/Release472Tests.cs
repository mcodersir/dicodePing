using ServiceLib.Tests.CoreConfig;
using Xunit;

namespace ServiceLib.Tests;
public class Release472Tests
{
    [Fact]
    public void LegacyFoxProfileUsesNativeSocksWithStableIdAndNoPrivateXrayBridge()
    {
        var file = Path.GetTempFileName();
        try {
            var id = Guid.NewGuid().ToString("N");
            File.WriteAllText(file, FoxProfiles.Template(id, "REC", 20100, 20200));
            var old = new ProfileItem { IndexId = "same-id", Subid = "same-sub", ConfigType = EConfigType.Custom, CoreType = ECoreType.Xray, Address = file, PreSocksPort = 20100 };
            var converted = FoxProfiles.ForConnection(old);
            Assert.Equal("same-id", converted.IndexId); Assert.Equal("same-sub", converted.Subid);
            Assert.Equal(EConfigType.SOCKS, converted.ConfigType); Assert.Equal(ECoreType.sing_box, converted.CoreType);
            Assert.Equal("127.0.0.1", converted.Address); Assert.Equal(7854, converted.Port); Assert.Null(converted.PreSocksPort);
            Assert.Equal(new FoxProfile(id, "REC", 7854), FoxProfiles.Read(converted));
            Assert.Equal(EConfigType.Custom, old.ConfigType);
            var config = CoreConfigTestFactory.CreateConfig(); config.TunModeItem.EnableTun = true;
            CoreConfigTestFactory.BindAppManagerConfig(config);
            Assert.Null(ConfigHandler.GetPreSocksItem(config, converted, ECoreType.sing_box));
            Assert.Equal("socks5://127.0.0.1:7854#Firefox-VPN", FoxProfiles.ShareUri);
        } finally { File.Delete(file); }
    }
    [Theory]
    [InlineData("configure tun interface: The system cannot find the file specified.", true)]
    [InlineData("failed to connect to Firefox", false)]
    [InlineData("configure tun interface: access denied", false)]
    public void OnlyMissingInterfaceStartupFailuresPermitBoundedAdapterRepair(string message, bool expected) =>
        Assert.Equal(expected, WindowsTunRuntime.IsMissingInterfaceFailure(message));

    [Fact]
    public void AdapterRepairOnlyRenamesAnOwnedTunAndPreservesRoutes()
    {
        var file = Path.GetTempFileName();
        try {
            File.WriteAllText(file, "{\"inbounds\":[{\"type\":\"tun\",\"interface_name\":\"other-vpn\"}]}");
            Assert.False(WindowsTunRuntime.PrepareRetry(file));
            File.WriteAllText(file, "{\"inbounds\":[{\"type\":\"tun\",\"interface_name\":\"DicodePing_old\",\"auto_route\":true}]}");
            Assert.True(WindowsTunRuntime.PrepareRetry(file));
            var root = JsonNode.Parse(File.ReadAllText(file))!;
            Assert.True(root["inbounds"]![0]!["auto_route"]!.GetValue<bool>());
            Assert.StartsWith(WindowsTunRuntime.InterfaceName + "_", root["inbounds"]![0]!["interface_name"]!.GetValue<string>());
        } finally { File.Delete(file); }
    }
}
