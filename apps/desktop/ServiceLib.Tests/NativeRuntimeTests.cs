using System.Diagnostics;
using ServiceLib.Services.CoreConfig;
using ServiceLib.Tests.CoreConfig;
using Xunit;

namespace ServiceLib.Tests;

public class NativeRuntimeTests
{
    [Theory]
    [InlineData(ECoreType.Xray, "normal")]
    [InlineData(ECoreType.Xray, "tun")]
    [InlineData(ECoreType.Xray, "probe")]
    [InlineData(ECoreType.sing_box, "normal")]
    [InlineData(ECoreType.sing_box, "tun")]
    [InlineData(ECoreType.sing_box, "probe")]
    public async Task BundledRuntimeAcceptsGeneratedConfiguration(ECoreType core, string mode)
    {
        var root = Environment.GetEnvironmentVariable("DICODE_RUNTIME_TEST_ROOT");
        if (string.IsNullOrEmpty(root)) Assert.Skip("Bundled native cores are validated in release CI.");
        var config = mode == "tun" ? CoreConfigTestFactory.CreateConfigWithTun(core, false) : CoreConfigTestFactory.CreateConfig(core);
        CoreConfigTestFactory.BindAppManagerConfig(config);
        var node = CoreConfigTestFactory.CreateVmessNode(core);
        var context = CoreConfigTestFactory.CreateContext(config, node, core);
        var result = core == ECoreType.Xray
            ? mode == "probe" ? new CoreConfigV2rayService(context).GenerateClientSpeedtestConfig(21512) : new CoreConfigV2rayService(context).GenerateClientConfigContent()
            : mode == "probe" ? new CoreConfigSingboxService(context).GenerateClientSpeedtestConfig(21512) : new CoreConfigSingboxService(context).GenerateClientConfigContent();
        Assert.True(result.Success, result.Msg);
        var file = Path.Combine(Path.GetTempPath(), $"dicode-native-{Guid.NewGuid():N}.json");
        await File.WriteAllTextAsync(file, result.Data!.ToString());
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
