using ServiceLib.Tests.CoreConfig;
using Xunit;

namespace ServiceLib.Tests;

public class Release498Tests
{
    [Fact]
    public void WindowsOrdinaryProfileGeneratesNativeTunWithItsOwnAdapter()
    {
        var config = CoreConfigTestFactory.CreateConfigWithTun(ECoreType.Xray, false);
        CoreConfigTestFactory.BindAppManagerConfig(config);
        var node = CoreConfigTestFactory.CreateVmessNode(ECoreType.Xray);
        var context = CoreConfigTestFactory.CreateContext(config, node, ECoreType.Xray) with { IsWindows = true };
        var result = new CoreConfigV2rayService(context).GenerateClientConfigContent();
        Assert.True(result.Success, result.Msg);
        var root = JsonNode.Parse(result.Data!.ToString()!)!;
        var tun = root["inbounds"]!.AsArray().Single(i => i?["protocol"]?.ToString() == "tun")!;
        Assert.Equal(WindowsTunRuntime.InterfaceName, tun["settings"]!["name"]!.ToString());
        Assert.Null(ConfigHandler.GetPreSocksItem(config, node, ECoreType.Xray));
    }

    [Fact]
    public void NativeAdapterRetryKeepsEveryRoutingAndTransportSetting()
    {
        var file = Path.GetTempFileName();
        try
        {
            File.WriteAllText(file, """{"inbounds":[{"protocol":"tun","settings":{"name":"DicodePing_old","MTU":1500,"autoSystemRoutingTable":["0.0.0.0/0"]}}],"outbounds":[{"protocol":"vless","tag":"proxy"}]}""");
            Assert.True(WindowsTunRuntime.PrepareRetry(file));
            var root = JsonNode.Parse(File.ReadAllText(file))!;
            Assert.StartsWith(WindowsTunRuntime.InterfaceName + "_", root["inbounds"]![0]!["settings"]!["name"]!.ToString());
            Assert.Equal(1500, root["inbounds"]![0]!["settings"]!["MTU"]!.GetValue<int>());
            Assert.Equal("vless", root["outbounds"]![0]!["protocol"]!.ToString());
        }
        finally { File.Delete(file); }
    }

    [Fact]
    public async Task HealthyProxyDoesNotOpenConnectionsToUnneededProviders()
    {
        var listener = new TcpListener(IPAddress.Loopback, 0);
        listener.Start();
        using var stop = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        var targets = new ConcurrentQueue<string>();
        var server = Task.Run(async () => {
            try
            {
                while (true)
                {
                    using var socket = await listener.AcceptTcpClientAsync(stop.Token);
                    using var stream = socket.GetStream();
                    using var reader = new StreamReader(stream, leaveOpen: true);
                    targets.Enqueue(await reader.ReadLineAsync(stop.Token) ?? "");
                    while (!string.IsNullOrEmpty(await reader.ReadLineAsync(stop.Token))) { }
                    await stream.WriteAsync(Encoding.ASCII.GetBytes("HTTP/1.1 204 No Content\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"), stop.Token);
                }
            }
            catch (OperationCanceledException) when (stop.IsCancellationRequested) { }
        });
        try
        {
            var proxy = new WebProxy($"http://127.0.0.1:{((IPEndPoint)listener.LocalEndpoint).Port}");
            var delay = await ProxyHealthProbe.MeasureAnyAsync(["http://first.invalid/generate_204", "http://unused.invalid/generate_204"], proxy, TimeSpan.FromSeconds(3));
            Assert.True(delay > 0);
            Assert.Equal(2, targets.Count);
            Assert.All(targets, target => Assert.Contains("first.invalid", target));
        }
        finally { stop.Cancel(); listener.Stop(); await server; }
    }
}
