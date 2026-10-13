using System.Diagnostics;
using ServiceLib.Services.CoreConfig;
using ServiceLib.Tests.CoreConfig;
using Xunit;

namespace ServiceLib.Tests;

public class NativeRuntimeTests
{
    [Fact]
    public void WindowsTunDriverCanBeLoaded()
    {
        var root = Environment.GetEnvironmentVariable("DICODE_RUNTIME_TEST_ROOT");
        if (!OperatingSystem.IsWindows() || string.IsNullOrEmpty(root)) Assert.Skip("Windows driver loading is validated in Windows release CI.");
        foreach (var relative in new[] { "wintun.dll", Path.Combine("bin", "xray", "wintun.dll"), Path.Combine("bin", "sing_box", "wintun.dll") })
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
            ["log"] = new JsonObject { ["level"] = "info" },
            ["inbounds"] = new JsonArray(new JsonObject { ["type"] = "tun", ["tag"] = "tun", ["interface_name"] = name,
                ["address"] = new JsonArray("172.30.250.1/30"), ["mtu"] = 1500, ["auto_route"] = false, ["strict_route"] = false, ["stack"] = "system" }),
            ["outbounds"] = new JsonArray(new JsonObject { ["type"] = "direct", ["tag"] = "direct" })
        }.ToJsonString());
        var binary = Path.Combine(root!, "bin", "sing_box", "sing-box.exe");
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
            Assert.Equal(0,process.ExitCode); Assert.Contains("26.10.9", await output);
        } finally { Directory.Delete(folder,true); }
    }

    [Theory]
    [InlineData(ECoreType.Xray, "normal")]
    [InlineData(ECoreType.Xray, "tun")]
    [InlineData(ECoreType.Xray, "probe")]
    [InlineData(ECoreType.Xray, "entry")]
    [InlineData(ECoreType.Xray, "sni")]
    [InlineData(ECoreType.Xray, "custom")]
    [InlineData(ECoreType.sing_box, "normal")]
    [InlineData(ECoreType.sing_box, "tun")]
    [InlineData(ECoreType.sing_box, "probe")]
    [InlineData(ECoreType.sing_box, "entry")]
    [InlineData(ECoreType.sing_box, "custom")]
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
