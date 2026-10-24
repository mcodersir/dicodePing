using System.Text.Json.Nodes;
using ServiceLib.Tests.CoreConfig;
using Xunit;

namespace ServiceLib.Tests;
public class Release471Tests
{
    [Theory]
    [InlineData(false, false)]
    [InlineData(false, true)]
    [InlineData(true, false)]
    [InlineData(true, true)]
    public async Task FoxProfileFromServerListAlwaysGetsATunBridgeAndMetrics(bool tun, bool legacy)
    {
        var folder = Path.Combine(Path.GetTempPath(), "dicode-471-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(folder);
        try {
            var source = Path.Combine(folder, "fox.json"); var output = Path.Combine(folder, "running.json");
            await File.WriteAllTextAsync(source, FoxProfiles.Template(Guid.NewGuid().ToString("N"), "REC", 20001, 20002));
            var config = CoreConfigTestFactory.CreateConfig();
            config.TunModeItem.EnableTun = tun; config.TunModeItem.EnableLegacyProtect = legacy;
            CoreConfigTestFactory.BindAppManagerConfig(config);
            var node = new ProfileItem { ConfigType = EConfigType.Custom, CoreType = ECoreType.Xray, Address = source, PreSocksPort = 20001 };
            var bridge = ConfigHandler.GetPreSocksItem(config, node, ECoreType.Xray);
            Assert.NotNull(bridge); Assert.Equal(ECoreType.Xray, bridge.CoreType); Assert.Equal(20001, bridge.Port);
            var result = await CoreConfigHandler.GenerateClientConfig(new CoreConfigContext { Node = node, AppConfig = config, RunCoreType = ECoreType.Xray }, output);
            Assert.True(result.Success, result.Msg);
            var raw = JsonNode.Parse(await File.ReadAllTextAsync(output))!;
            Assert.Null(raw["dicodeFox"]);
            Assert.NotNull(raw["metrics"]?["listen"]);
            Assert.True(raw["policy"]!["system"]!["statsOutboundUplink"]!.GetValue<bool>());
            Assert.True(raw["policy"]!["system"]!["statsOutboundDownlink"]!.GetValue<bool>());
            Assert.Equal(20002, raw["outbounds"]![0]!["settings"]!["servers"]![0]!["port"]!.GetValue<int>());
            Assert.NotNull(JsonNode.Parse(await File.ReadAllTextAsync(source))!["dicodeFox"]);
        } finally { Directory.Delete(folder, true); }
    }
}
