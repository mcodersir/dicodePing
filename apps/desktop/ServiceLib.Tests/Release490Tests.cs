using ServiceLib.Tests.CoreConfig;
using Xunit;

namespace ServiceLib.Tests;

public class Release490Tests
{
    [Fact]
    public async Task ExplicitConnectWaitsForAnInFlightReloadInsteadOfReportingAnEarlyFailure()
    {
        // Exercise the real reload queue without constructing unrelated UI commands/services.
        var model = (ServiceLib.ViewModels.MainWindowViewModel)System.Runtime.CompilerServices.RuntimeHelpers.GetUninitializedObject(typeof(ServiceLib.ViewModels.MainWindowViewModel));
        model.DesignMode = true;
        using var gate = new SemaphoreSlim(1, 1);
        typeof(ServiceLib.ViewModels.MainWindowViewModel).GetField("_reloadSemaphore", BindingFlags.Instance | BindingFlags.NonPublic)!.SetValue(model, gate);
        await gate.WaitAsync();
        var connection = model.Reload(forceStart: true);
        try { Assert.False(connection.IsCompleted); }
        finally { gate.Release(); }
        await connection.WaitAsync(TimeSpan.FromSeconds(3));
        Assert.Equal(1, gate.CurrentCount);
    }

    [Theory]
    [InlineData("WARP", "Cloudflare WARP Adapter", false)]
    [InlineData("Ethernet", "WireGuard Tunnel", false)]
    [InlineData("DicodePing_12", "Wintun Userspace Tunnel", false)]
    [InlineData("vEthernet", "Hyper-V Virtual Ethernet Adapter", false)]
    [InlineData("Ethernet", "Intel Ethernet Connection", true)]
    [InlineData("Wi-Fi", "Intel Wireless", true)]
    public void UplinkSelectionExcludesOtherVpns(string name, string description, bool expected) =>
        Assert.Equal(expected, PhysicalUplink.IsCandidate(name, description, NetworkInterfaceType.Ethernet, OperationalStatus.Up, true));

    [Fact]
    public void UplinkMustBeConnectedAndHaveAGateway()
    {
        Assert.False(PhysicalUplink.IsCandidate("Ethernet", "Intel", NetworkInterfaceType.Ethernet, OperationalStatus.Down, true));
        Assert.False(PhysicalUplink.IsCandidate("Ethernet", "Intel", NetworkInterfaceType.Ethernet, OperationalStatus.Up, false));
    }

    [Fact]
    public void AdapterCollisionCanBeRetriedWithoutTouchingForeignAdapters()
    {
        Assert.True(WindowsTunRuntime.IsMissingInterfaceFailure("configure tun interface: create adapter: Cannot create a file when that file already exists. | open existing adapter: Element not found."));
        Assert.False(WindowsTunRuntime.IsMissingInterfaceFailure("listen tcp 127.0.0.1:10808: bind: address already in use"));
        var path = Path.GetTempFileName();
        try {
            File.WriteAllText(path, "{\"inbounds\":[{\"type\":\"tun\",\"interface_name\":\"WARP\"}]}");
            Assert.False(WindowsTunRuntime.PrepareRetry(path));
            File.WriteAllText(path, "{\"inbounds\":[{\"type\":\"tun\",\"interface_name\":\"DicodePing_12\",\"route_address\":[\"198.18.0.1/32\"]}]}");
            Assert.True(WindowsTunRuntime.PrepareRetry(path)); var first = File.ReadAllText(path);
            Assert.True(WindowsTunRuntime.PrepareRetry(path)); Assert.NotEqual(first, File.ReadAllText(path));
            Assert.Contains("198.18.0.1/32", File.ReadAllText(path));
        } finally { File.Delete(path); }
    }

    [Fact]
    public async Task OccupiedMixedPortUsesAnIndependentRuntimePortWithoutChangingSavedSettings()
    {
        var listener = new TcpListener(IPAddress.Loopback, 0); listener.Start();
        try {
            var occupied = ((IPEndPoint)listener.LocalEndpoint).Port;
            var config = CoreConfigTestFactory.CreateConfig();
            config.Inbound[0].LocalPort = occupied; config.TunModeItem.EnableTun = true;
            CoreConfigTestFactory.BindAppManagerConfig(config);
            SQLiteHelper.Instance.CreateTable<FullConfigTemplateItem>(); SQLiteHelper.Instance.CreateTable<DNSItem>();
            SQLiteHelper.Instance.CreateTable<RoutingItem>(); SQLiteHelper.Instance.CreateTable<ProfileItem>();
            await SQLiteHelper.Instance.ReplaceAsync(new RoutingItem { Id = "490-default", IsActive = true, RuleSet = "[]" });
            var result = await CoreConfigContextBuilder.BuildAll(config, CoreConfigTestFactory.CreateVmessNode(ECoreType.Xray));
            Assert.True(result.Success);
            var port = result.MainResult.Context.AppConfig.Inbound[0].LocalPort;
            Assert.NotEqual(occupied, port); Assert.Equal(occupied, config.Inbound[0].LocalPort);
            Assert.Equal(occupied, result.MainResult.Context.RequestedLocalPort);
            if (result.PreSocksResult is not null) Assert.Equal(port, result.PreSocksResult.Context.Node.Port);
            using var stillAvailable = new TcpClient(); await stillAvailable.ConnectAsync(IPAddress.Loopback, occupied);
            using var accepted = await listener.AcceptTcpClientAsync(); Assert.True(accepted.Connected);
        } finally { listener.Stop(); }
    }

    [Fact]
    public async Task ASettingsChangeCannotGiveTheBridgeTheMainCoresListenPort()
    {
        var config = CoreConfigTestFactory.CreateConfig(); config.TunModeItem.EnableTun = true;
        config.CoreBasicItem.BindInterface = "";
        CoreConfigTestFactory.BindAppManagerConfig(config);
        var bridge = CoreConfigTestFactory.CreateSocksNode(ECoreType.sing_box, "bridge", "bridge");
        bridge.Address = Global.Loopback; bridge.Port = 10808;
        SQLiteHelper.Instance.CreateTable<FullConfigTemplateItem>();
        SQLiteHelper.Instance.CreateTable<DNSItem>();
        SQLiteHelper.Instance.CreateTable<RoutingItem>();
        SQLiteHelper.Instance.CreateTable<ProfileItem>();
        await SQLiteHelper.Instance.ReplaceAsync(new RoutingItem { Id = "490-default", IsActive = true, RuleSet = "[]" });
        var built = await CoreConfigContextBuilder.Build(config, bridge);
        config.Inbound[0].LocalPort = 12000;
        var result = new CoreConfigSingboxService(built.Context).GenerateClientConfigContent();
        Assert.True(result.Success, result.Msg);
        var json = JsonNode.Parse(result.Data.ToString())!;
        Assert.DoesNotContain(json["inbounds"]!.AsArray(), x => x?["type"]?.ToString() == "mixed");
        Assert.Contains(json["inbounds"]!.AsArray(), x => x?["type"]?.ToString() == "tun");
        Assert.Equal(10808, built.Context.AppConfig.Inbound[0].LocalPort);
    }
}
