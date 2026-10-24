using System.IO.Compression;
using ServiceLib.Tests.CoreConfig;
using Xunit;

namespace ServiceLib.Tests;

public class Release499Tests
{
    [Fact]
    public async Task SavedFoxSocksProfileUsesXrayTunWithoutAnExtraRuntime()
    {
        var config = CoreConfigTestFactory.CreateConfigWithTun(ECoreType.Xray, false);
        config.TunModeItem.EnableLegacyProtect = true;
        CoreConfigTestFactory.BindAppManagerConfig(config);
        var node = new ProfileItem { IndexId = "saved", ConfigType = EConfigType.SOCKS, CoreType = ECoreType.sing_box,
            Address = "127.0.0.1", Port = 7854 };
        node.SetProtocolExtra(new ProtocolExtraItem { FoxAccountId = Guid.NewGuid().ToString("N"), FoxCountry = "REC" });
        SQLiteHelper.Instance.CreateTable<FullConfigTemplateItem>();
        SQLiteHelper.Instance.CreateTable<DNSItem>();
        SQLiteHelper.Instance.CreateTable<RoutingItem>();
        SQLiteHelper.Instance.CreateTable<ProfileItem>();
        await SQLiteHelper.Instance.ReplaceAsync(new RoutingItem { Id = "499-default", IsActive = true, RuleSet = "[]" });
        var built = await CoreConfigContextBuilder.BuildAll(config, node);
        Assert.True(built.Success, string.Join(";", built.CombinedValidatorResult.Errors));
        Assert.Equal(ECoreType.Xray, built.MainResult.Context.RunCoreType);
        Assert.Null(built.PreSocksResult);
        var generated = new CoreConfigV2rayService(built.MainResult.Context with { IsWindows = true }).GenerateClientConfigContent();
        Assert.True(generated.Success, generated.Msg);
        var json = JsonNode.Parse(generated.Data!.ToString()!)!;
        Assert.Contains(json["inbounds"]!.AsArray(), i => i?["protocol"]?.ToString() == "tun");
        Assert.Equal("socks", json["outbounds"]![0]!["protocol"]!.ToString());
    }

    [Fact]
    public void DiagnosticZipIncludesLogsButExcludesVaultAndConfiguration()
    {
        var previous = Environment.GetEnvironmentVariable("DICODE_DATA_DIR");
        var folder = Path.Combine(Path.GetTempPath(), "dicode-diagnostics-" + Guid.NewGuid().ToString("N"));
        Environment.SetEnvironmentVariable("DICODE_DATA_DIR", folder);
        CoreConfigTestFactory.BindAppManagerConfig(CoreConfigTestFactory.CreateConfig());
        try {
            File.WriteAllText(Utils.GetLogPath("fixture.txt"), "startup failed; password=sentinel-password Bearer sentinel-token person@example.com");
            File.WriteAllText(Path.Combine(folder, "accounts.enc"), "sentinel-vault");
            using var stream = new MemoryStream();
            DiagnosticArchive.Write(stream);
            stream.Position = 0;
            using var zip = new ZipArchive(stream);
            Assert.Contains(zip.Entries, e => e.FullName == "system.txt");
            Assert.DoesNotContain(zip.Entries, e => e.FullName.Contains("accounts") || e.FullName.Contains("config"));
            using var reader = new StreamReader(zip.GetEntry("logs/fixture.txt")!.Open());
            var logs = reader.ReadToEnd();
            Assert.Contains("startup failed", logs);
            Assert.DoesNotContain("sentinel-password", logs);
            Assert.DoesNotContain("sentinel-token", logs);
            Assert.DoesNotContain("person@example.com", logs);
        } finally { Environment.SetEnvironmentVariable("DICODE_DATA_DIR", previous); if (Directory.Exists(folder)) Directory.Delete(folder, true); }
    }
}
