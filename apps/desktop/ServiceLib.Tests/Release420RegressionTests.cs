using System.Globalization;
using ServiceLib.Tests.CoreConfig;
using Xunit;

namespace ServiceLib.Tests;

public class Release420RegressionTests
{
    [Theory]
    [InlineData(ECoreType.mihomo, "Mihomo Meta v1.19.32 linux amd64", "1.19.32")]
    [InlineData(ECoreType.mihomo, "Mihomo v1.19.32 linux amd64 with go1.25.0", "1.19.32")]
    [InlineData(ECoreType.sing_box, "sing-box version 1.14.2\nEnvironment: go1.25.0", "1.14.2")]
    [InlineData(ECoreType.Xray, "Xray 26.10.7 (Xray, Penetrates Everything.)", "26.10.7")]
    public void RuntimeVersionUsesCoreVersionRatherThanCompilerVersion(ECoreType core, string output, string expected)
    {
        Assert.Equal(new SemanticVersion(expected), CoreRuntimeVersion.Parse(core, output));
    }

    [Fact]
    public async Task AppDataReceivesNewBundleOnceAndKeepsSubsequentCoreUpdates()
    {
        var root = Path.Combine(Path.GetTempPath(), Guid.NewGuid().ToString("N"));
        var source = Path.Combine(root, "source"); var dest = Path.Combine(root, "dest");
        Directory.CreateDirectory(Path.Combine(source, "mihomo"));
        Directory.CreateDirectory(Path.Combine(dest, "mihomo"));
        var file = Path.Combine(dest, "mihomo", "mihomo");
        try
        {
            await File.WriteAllTextAsync(Path.Combine(source, "mihomo", "mihomo"), "new bundled core");
            await File.WriteAllTextAsync(file, "old installed core");
            await BundledRuntimeInstaller.InstallAsync(source, dest, "4.2.0");
            Assert.Equal("new bundled core", await File.ReadAllTextAsync(file));
            await File.WriteAllTextAsync(file, "user upgraded core");
            await BundledRuntimeInstaller.InstallAsync(source, dest, "4.2.0");
            Assert.Equal("user upgraded core", await File.ReadAllTextAsync(file));
            await BundledRuntimeInstaller.InstallAsync(source, dest, "4.3.0");
            Assert.Equal("new bundled core", await File.ReadAllTextAsync(file));
        }
        finally { Directory.Delete(root, true); }
    }

    [Fact]
    public void AllEnglishResourceKeysHavePersianEntriesAndMatchingFormatParameters()
    {
        var resources = ResUI.ResourceManager;
        var english = resources.GetResourceSet(CultureInfo.InvariantCulture, true, false)!;
        var persian = resources.GetResourceSet(CultureInfo.GetCultureInfo("fa"), true, false)!;
        foreach (System.Collections.DictionaryEntry entry in english)
        {
            var localized = persian.GetString((string)entry.Key);
            Assert.False(string.IsNullOrWhiteSpace(localized), $"Missing Persian translation: {entry.Key}");
            string[] Parameters(string text) => System.Text.RegularExpressions.Regex.Matches(text, @"\{(\d+)(?:[^}]*)\}").Select(x => x.Groups[1].Value).Order().ToArray();
            Assert.Equal(Parameters(entry.Value?.ToString() ?? ""), Parameters(localized!));
        }
    }

    [Fact]
    public async Task FailedProbeReplacesAnOldSuccessfulMeasurement()
    {
        var id = Guid.NewGuid().ToString("N");
        ProfileExManager.Instance.SetTestDelay(id, 24);
        ProfileExManager.Instance.SetTestSpeed(id, 12);
        ProfileExManager.Instance.SetTestDelay(id, -1);
        ProfileExManager.Instance.SetTestSpeed(id, 0);
        var row = (await ProfileExManager.Instance.GetProfileExs()).Single(x => x.IndexId == id);
        Assert.Equal(-1, row.Delay); Assert.Equal(0, row.Speed);
    }
}
