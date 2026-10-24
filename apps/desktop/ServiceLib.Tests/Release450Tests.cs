using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using ServiceLib.Services;
using ServiceLib.Tests.CoreConfig;
using Xunit;

namespace ServiceLib.Tests;

public class Release450Tests
{
    [Theory]
    [InlineData("DE 203.0.113.1", "DE")]
    [InlineData("Congo, Republic of", "CG")]
    [InlineData("United States 203.0.113.1", "US")]
    [InlineData("🇦🇽 203.0.113.1", "AX")]
    [InlineData("🇨🇼", "CW")]
    [InlineData("UK 203.0.113.1", "GB")]
    [InlineData("xk", "XK")]
    [InlineData("Failed to run core", "")]
    public void LocationsIdentifyTheirCountryWithoutGuessingOrdinaryWords(string text, string code) => Assert.Equal(code, CountryCodes.FromLocation(text));

    [Fact]
    public void OtherEngineJsonNeverReturnsNullProfilesOrLeadsToImportNullReferences()
    {
        CoreConfigTestFactory.BindAppManagerConfig(CoreConfigTestFactory.CreateConfig());
        const string raw = """{"remarks":"Cisco import","inbounds":[{"type":"mixed","listen":"127.0.0.1","listen_port":21080}],"endpoints":[{"type":"openconnect","tag":"proxy","server":"https://vpn.example.com"}],"route":{"final":"proxy"}}""";
        Assert.Empty(ServiceLib.Handler.Fmt.V2rayFmt.ResolveToCustom(raw, null));
        var profiles = ServiceLib.Handler.Fmt.SingboxFmt.ResolveToCustom(raw, null);
        var profile = Assert.Single(profiles);
        try {
            Assert.NotNull(profile);
            Assert.Equal(ECoreType.sing_box, profile.CoreType);
            Assert.Equal(21080, profile.PreSocksPort);
            Assert.Equal("Cisco import", profile.Remarks);
            Assert.DoesNotContain("remarks", File.ReadAllText(profile.Address));
        } finally { File.Delete(profile.Address); }
    }

    [Fact]
    public async Task ParallelPoolAndImportTransactionsCommitWithoutInvalidSavepoints()
    {
        var previous = Environment.GetEnvironmentVariable("DICODE_DATA_DIR");
        var folder = Path.Combine(Path.GetTempPath(), "dicode-db-" + Guid.NewGuid());
        Directory.CreateDirectory(Path.Combine(folder, "guiConfigs"));
        Environment.SetEnvironmentVariable("DICODE_DATA_DIR", folder);
        var db = new SQLiteHelper();
        try {
            db.CreateTable<ProfileItem>();
            await Task.WhenAll(Enumerable.Range(0, 64).Select(async i => {
                await db.InsertAllAsync(new[] { new ProfileItem { IndexId = "import-" + i, Subid = "import" } });
                await db.ReplaceServerPoolAsync("pool-" + i, [new ProfileItem { IndexId = "pool-node-" + i, Subid = "pool-" + i }], null);
            }));
            Assert.Equal(128, await db.TableAsync<ProfileItem>().CountAsync());
        } finally { await db.DisposeDbConnectionAsync(); Environment.SetEnvironmentVariable("DICODE_DATA_DIR", previous); Directory.Delete(folder, true); }
    }

    [Theory]
    [InlineData("snell")]
    [InlineData("anytls")]
    [InlineData("ssh")]
    [InlineData("openconnect")]
    [InlineData("openvpn-client")]
    public async Task RemovedEngineTemplatesReportUnsupportedInsteadOfSpawningMissingRuntime(string kind)
    {
        Assert.Throws<NotSupportedException>(() => NativeProfileTemplates.Build(kind, "vpn.example.com", 443, "user", "password"));
        await Task.CompletedTask;
    }
}
