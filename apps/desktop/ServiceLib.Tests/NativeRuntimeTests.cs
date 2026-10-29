using System.Diagnostics;
using ServiceLib.Services.CoreConfig;
using ServiceLib.Tests.CoreConfig;
using Xunit;

namespace ServiceLib.Tests;

public class NativeRuntimeTests
{
    [Fact]
    public async Task WindowsTunRoutesHttpThroughXrayAndCountsBothDirections()
    {
        var root = Environment.GetEnvironmentVariable("DICODE_RUNTIME_TEST_ROOT");
        if (!OperatingSystem.IsWindows() || string.IsNullOrEmpty(root)) Assert.Skip("Routed Windows TUN traffic is validated in release CI.");
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(50)); var ct = deadline.Token;
        var listener = new TcpListener(IPAddress.Loopback, 0); listener.Start();
        var fixturePort = ((IPEndPoint)listener.LocalEndpoint).Port;
        var xrayPort = Utils.GetFreePort(24000); var metricsPort = Utils.GetFreePort(xrayPort + 1);
        var name = "DicodePing_CI_" + Guid.NewGuid().ToString("N")[..8];
        var xfile = Path.Combine(Path.GetTempPath(), name + "-xray.json"); var sfile = Path.Combine(Path.GetTempPath(), name + "-tun.json");
        var fixture = Task.Run(async () => {
            using var client = await listener.AcceptTcpClientAsync(ct); var stream = client.GetStream();
            var hello = new byte[2]; await stream.ReadExactlyAsync(hello, ct); Assert.Equal(5, hello[0]);
            await stream.ReadExactlyAsync(new byte[hello[1]], ct); await stream.WriteAsync(new byte[] { 5, 0 }, ct);
            var request = new byte[4]; await stream.ReadExactlyAsync(request, ct); Assert.Equal(1, request[1]);
            var length = request[3] switch { 1 => 4, 4 => 16, 3 => stream.ReadByte(), _ => throw new IOException("Invalid address") };
            await stream.ReadExactlyAsync(new byte[length + 2], ct); await stream.WriteAsync(new byte[] { 5, 0, 0, 1, 127, 0, 0, 1, 0, 0 }, ct);
            var header = new StringBuilder(); var one = new byte[1];
            while (!header.ToString().EndsWith("\r\n\r\n")) { await stream.ReadExactlyAsync(one, ct); header.Append((char)one[0]); }
            Assert.StartsWith("GET /routed", header.ToString());
            await stream.WriteAsync(Encoding.ASCII.GetBytes("HTTP/1.1 200 OK\r\nContent-Length: 9\r\nConnection: close\r\n\r\ntunnel-ok"), ct);
        }, ct);
        await File.WriteAllTextAsync(xfile, $$$$"""
        {"log":{"loglevel":"warning"},"inbounds":[{"listen":"127.0.0.1","port":{{{{xrayPort}}}},"protocol":"socks","settings":{"auth":"noauth"}}],
         "outbounds":[{"tag":"proxy","protocol":"socks","settings":{"servers":[{"address":"127.0.0.1","port":{{{{fixturePort}}}}}]}}],
         "stats":{},"metrics":{"listen":"127.0.0.1:{{{{metricsPort}}}}"},"policy":{"system":{"statsOutboundUplink":true,"statsOutboundDownlink":true}}}
        """, ct);
        await File.WriteAllTextAsync(sfile, $$$$"""
        {"log":{"loglevel":"info"},"inbounds":[{"protocol":"tun","tag":"tun","settings":{"name":"{{{{name}}}}","gateway":["172.30.250.1/30"],"MTU":1500,"autoSystemRoutingTable":["198.18.0.1/32"],"autoSystemDnsToGateway":false}}],
         "outbounds":[{"protocol":"socks","tag":"proxy","settings":{"servers":[{"address":"127.0.0.1","port":{{{{xrayPort}}}}}]}}]}
        """, ct);
        var xbinary = Path.Combine(root!, "bin", "xray", "xray.exe"); var sbinary = Path.Combine(root!, "bin", "xray", "xray.exe");
        using var xray = new ProcessService(xbinary, "run -c " + xfile.AppendQuotes(), Path.GetDirectoryName(xbinary)!, true, false, null, (_,_)=>Task.CompletedTask);
        using var tun = new ProcessService(sbinary, "run -c " + sfile.AppendQuotes(), Path.GetDirectoryName(sbinary)!, true, false, null, (_,_)=>Task.CompletedTask);
        try {
            await xray.StartAsync(); await Task.Delay(500, ct); Assert.False(xray.HasExited, xray.RecentOutput);
            await tun.StartAsync(); await tun.WaitForStartupAsync(TimeSpan.FromSeconds(35));
            using var http = new HttpClient(new SocketsHttpHandler { UseProxy = false }) { Timeout = TimeSpan.FromSeconds(10) };
            Assert.Equal("tunnel-ok", await http.GetStringAsync("http://198.18.0.1:18080/routed", ct)); await fixture;
            var metrics = JsonNode.Parse(await http.GetStringAsync($"http://127.0.0.1:{metricsPort}/debug/vars", ct))!;
            Assert.True(metrics["stats"]!["outbound"]!["proxy"]!["uplink"]!.GetValue<long>() > 0);
            Assert.True(metrics["stats"]!["outbound"]!["proxy"]!["downlink"]!.GetValue<long>() > 0);
        } finally { await tun.StopAsync(); await xray.StopAsync(); listener.Stop(); File.Delete(sfile); File.Delete(xfile); }
    }
    [Fact]
    public void WindowsTunDriverCanBeLoaded()
    {
        var root = Environment.GetEnvironmentVariable("DICODE_RUNTIME_TEST_ROOT");
        if (!OperatingSystem.IsWindows() || string.IsNullOrEmpty(root)) Assert.Skip("Windows driver loading is validated in Windows release CI.");
        foreach (var relative in new[] { "wintun.dll", Path.Combine("bin", "xray", "wintun.dll") })
        {
            var handle = System.Runtime.InteropServices.NativeLibrary.Load(Path.Combine(root!, relative));
            try { Assert.NotEqual(IntPtr.Zero, System.Runtime.InteropServices.NativeLibrary.GetExport(handle, "WintunCreateAdapter")); }
            finally { System.Runtime.InteropServices.NativeLibrary.Free(handle); }
        }
    }

    [Fact]
    public async Task WindowsTunActuallyStartsAndGetsItsIpBeforeReportingReady()
    {
        var root = Environment.GetEnvironmentVariable("DICODE_RUNTIME_TEST_ROOT");
        if (!OperatingSystem.IsWindows() || string.IsNullOrEmpty(root)) Assert.Skip("Live Windows TUN is exercised in release CI.");
        var name = "DicodePing_CI_" + Guid.NewGuid().ToString("N")[..8];
        var path = Path.Combine(Path.GetTempPath(), name + ".json");
        await File.WriteAllTextAsync(path, new JsonObject {
            ["log"] = new JsonObject { ["loglevel"] = "info" },
            ["inbounds"] = new JsonArray(new JsonObject { ["protocol"] = "tun", ["tag"] = "tun", ["settings"] = new JsonObject { ["name"] = name, ["gateway"] = new JsonArray("172.30.250.1/30"), ["MTU"] = 1500, ["autoSystemDnsToGateway"] = false } }),
            ["outbounds"] = new JsonArray(new JsonObject { ["protocol"] = "freedom", ["tag"] = "direct" })
        }.ToJsonString());
        var binary = Path.Combine(root!, "bin", "xray", "xray.exe");
        using var child = new ProcessService(binary, "run -c " + path.AppendQuotes(), Path.GetDirectoryName(binary)!, true, false, null, (_, _) => Task.CompletedTask);
        try {
            await child.StartAsync(); await child.WaitForStartupAsync(TimeSpan.FromSeconds(35));
            Assert.True(child.StartupCompleted); Assert.False(child.HasExited);
            var adapter = NetworkInterface.GetAllNetworkInterfaces().Single(n => n.Name == name);
            Assert.Contains(adapter.GetIPProperties().UnicastAddresses, a => a.Address.ToString() == "172.30.250.1");
            await Task.Delay(1500); Assert.False(child.HasExited);
        } finally { await child.StopAsync(); File.Delete(path); }
    }

    [Fact]
    public async Task FoxTemplateIsAcceptedByBundledXrayWithoutExposingAccountTokens()
    {
        var root = Environment.GetEnvironmentVariable("DICODE_RUNTIME_TEST_ROOT");
        if (string.IsNullOrEmpty(root)) Assert.Skip("Bundled native cores are validated in release CI.");
        var content = JsonNode.Parse(FoxProfiles.Template(Guid.NewGuid().ToString("N"), "DE", 21512, 21513))!.AsObject(); content.Remove("dicodeFox");
        var file = Path.Combine(Path.GetTempPath(), $"dicode-fox-native-{Guid.NewGuid():N}.json"); await File.WriteAllTextAsync(file, content.ToJsonString());
        try {
            var binary = Path.Combine(root!, "bin", "xray", "xray" + (OperatingSystem.IsWindows() ? ".exe" : ""));
            using var process = new Process { StartInfo = new ProcessStartInfo(binary) { RedirectStandardOutput = true, RedirectStandardError = true, UseShellExecute = false } };
            foreach (var arg in new[] { "run", "-test", "-c", file }) process.StartInfo.ArgumentList.Add(arg);
            process.Start(); var stdout = process.StandardOutput.ReadToEndAsync(); var stderr = process.StandardError.ReadToEndAsync();
            using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(20));
            try { await process.WaitForExitAsync(timeout.Token); } catch { process.Kill(true); throw; }
            Assert.True(process.ExitCode == 0, await stdout + await stderr);
        } finally { File.Delete(file); }
    }

    [Fact]
    public async Task WindowsAliasRepairsCorruptCopiesAndRunsVerifiedBundledExecutable()
    {
        var root = Environment.GetEnvironmentVariable("DICODE_RUNTIME_TEST_ROOT");
        if (!OperatingSystem.IsWindows() || string.IsNullOrEmpty(root)) Assert.Skip("Windows alias launch is validated in Windows release CI.");
        var folder = Path.Combine(Path.GetTempPath(), $"dicode-alias-{Guid.NewGuid():N}"); Directory.CreateDirectory(folder);
        try {
            var original = Path.Combine(folder, "xray.exe"); File.Copy(Path.Combine(root!, "bin", "xray", "xray.exe"), original);
            var stale = Path.Combine(folder, "p-xray-p.exe"); await File.WriteAllTextAsync(stale, "incomplete file");
            var method = typeof(CoreInfoManager).GetMethod("GetXrayAliasExecFile", BindingFlags.Static | BindingFlags.NonPublic)!;
            var alias = (string)method.Invoke(null, [original])!;
            Assert.Equal(stale,alias); Assert.Equal(SHA256.HashData(File.ReadAllBytes(original)),SHA256.HashData(File.ReadAllBytes(alias)));
            using var process = new Process { StartInfo = new ProcessStartInfo(alias, "version") { RedirectStandardOutput = true, RedirectStandardError = true, UseShellExecute = false } };
            process.Start(); var output = process.StandardOutput.ReadToEndAsync(); using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(10));
            try { await process.WaitForExitAsync(timeout.Token); } catch { process.Kill(true); throw; }
            Assert.Equal(0,process.ExitCode); Assert.Contains("26.10.27", await output);
        } finally { Directory.Delete(folder,true); }
    }

    [Theory]
    [InlineData(ECoreType.Xray, "normal")]
    [InlineData(ECoreType.Xray, "tun")]
    [InlineData(ECoreType.Xray, "probe")]
    [InlineData(ECoreType.Xray, "entry")]
    [InlineData(ECoreType.Xray, "sni")]
    [InlineData(ECoreType.Xray, "custom")]
    public async Task BundledRuntimeAcceptsGeneratedConfiguration(ECoreType core, string mode)
    {
        var root = Environment.GetEnvironmentVariable("DICODE_RUNTIME_TEST_ROOT");
        if (string.IsNullOrEmpty(root)) Assert.Skip("Bundled native cores are validated in release CI.");
        var config = mode == "tun" ? CoreConfigTestFactory.CreateConfigWithTun(core, false) : CoreConfigTestFactory.CreateConfig(core);
        CoreConfigTestFactory.BindAppManagerConfig(config);
        var node = CoreConfigTestFactory.CreateVmessNode(core);
        if (mode == "sni") { node.StreamSecurity = "tls"; SniBlockPreset.Apply(node); }
        var context = CoreConfigTestFactory.CreateContext(config, node, core);
        if (mode == "entry") { config.EntryHopItem.Enabled = true; context = context with { UseEntryHop = true }; }
        var result = core == ECoreType.Xray
            ? mode == "probe" ? new CoreConfigV2rayService(context).GenerateClientSpeedtestConfig(21512) : new CoreConfigV2rayService(context).GenerateClientConfigContent()
            : mode == "probe" ? new CoreConfigSingboxService(context).GenerateClientSpeedtestConfig(21512) : new CoreConfigSingboxService(context).GenerateClientConfigContent();
        Assert.True(result.Success, result.Msg);
        var file = Path.Combine(Path.GetTempPath(), $"dicode-native-{Guid.NewGuid():N}.json");
        var content = mode == "custom" ? CustomProbeConfiguration.Build(result.Data!.ToString()!, core, 21512) : EntryHopConfiguration.Apply(result.Data!.ToString()!, context);
        await File.WriteAllTextAsync(file, content);
        try
        {
            var binary = Path.Combine(root!, "bin", core.ToString().ToLowerInvariant(), core == ECoreType.Xray ? "xray" : "sing-box");
            if (OperatingSystem.IsWindows()) binary += ".exe";
            using var process = new Process { StartInfo = new ProcessStartInfo(binary) { RedirectStandardOutput = true, RedirectStandardError = true, UseShellExecute = false } };
            if (core == ECoreType.Xray) { process.StartInfo.ArgumentList.Add("run"); process.StartInfo.ArgumentList.Add("-test"); }
            else process.StartInfo.ArgumentList.Add("check");
            process.StartInfo.ArgumentList.Add("-c"); process.StartInfo.ArgumentList.Add(file);
            process.StartInfo.Environment["XRAY_LOCATION_ASSET"] = Path.Combine(root!, "bin");
            process.Start();
            var stdout = process.StandardOutput.ReadToEndAsync(); var stderr = process.StandardError.ReadToEndAsync();
            using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(20));
            try { await process.WaitForExitAsync(timeout.Token); }
            catch { process.Kill(true); throw; }
            Assert.True(process.ExitCode == 0, await stdout + "\n" + await stderr);
        }
        finally { File.Delete(file); }
    }
}
