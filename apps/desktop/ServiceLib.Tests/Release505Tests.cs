using ServiceLib.Services;
using Xunit;

namespace ServiceLib.Tests;

public class Release505Tests
{
    [Fact]
    public async Task RuntimeInstallPreservesSingboxAndUnchangedExecutableAcrossUpgrades()
    {
        var root = Path.Combine(Path.GetTempPath(), "dicode505-" + Guid.NewGuid().ToString("N"));
        var source = Path.Combine(root, "package"); var target = Path.Combine(root, "runtime");
        var binary = Path.Combine(source, "sing_box", "sing-box");
        Directory.CreateDirectory(Path.GetDirectoryName(binary)!);
        await File.WriteAllTextAsync(binary, "bundled sing-box");
        try
        {
            await BundledRuntimeInstaller.InstallAsync(source, target, "5.0.3");
            var installed = Path.Combine(target, "sing_box", "sing-box");
            var stamp = DateTime.UtcNow.AddDays(-1); File.SetLastWriteTimeUtc(installed, stamp);
            var actualStamp = File.GetLastWriteTimeUtc(installed);
            var manual = Path.Combine(target, "sing_box", "user-runtime"); await File.WriteAllTextAsync(manual, "keep");
            await BundledRuntimeInstaller.InstallAsync(source, target, "5.0.5");
            Assert.True(File.Exists(binary)); Assert.True(File.Exists(installed)); Assert.True(File.Exists(manual));
            Assert.Equal(actualStamp, File.GetLastWriteTimeUtc(installed));
            await File.WriteAllTextAsync(binary, "new bundled sing-box");
            await BundledRuntimeInstaller.InstallAsync(source, target, "5.0.6");
            Assert.Equal("new bundled sing-box", await File.ReadAllTextAsync(installed));
        }
        finally { Directory.Delete(root, true); }
    }

    [Fact]
    public async Task RecoverableErrorBeforeStartupDoesNotKillHealthyCore()
    {
        if (OperatingSystem.IsWindows()) return;
        using var process = new ProcessService("/bin/sh", "-c \"echo '[Error] app/router: process lookup unavailable'; echo 'sing-box started'; sleep 3\"",
            Path.GetTempPath(), true, false, null, (_, _) => Task.CompletedTask);
        try
        {
            await process.StartAsync(); await process.WaitForStartupAsync(TimeSpan.FromSeconds(2));
            Assert.True(process.StartupCompleted); Assert.False(process.HasExited);
            Assert.Contains("[Error]", process.RecentOutput);
        }
        finally { await process.StopAsync(); }
    }
}
