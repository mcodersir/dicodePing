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
    public async Task BundledRuntimeAcceptsNativeTemplatesAndIsolatedProbes(string kind)
    {
        var root = Environment.GetEnvironmentVariable("DICODE_RUNTIME_TEST_ROOT");
        if (string.IsNullOrEmpty(root)) Assert.Skip("Native runtimes are validated in release CI.");
        CoreConfigTestFactory.BindAppManagerConfig(CoreConfigTestFactory.CreateConfig());
        using var key = RSA.Create(2048);
        var request = new CertificateRequest("CN=Dicode test CA", key, HashAlgorithmName.SHA256, RSASignaturePadding.Pkcs1);
        request.CertificateExtensions.Add(new X509BasicConstraintsExtension(true, false, 0, true));
        using var cert = request.CreateSelfSigned(DateTimeOffset.UtcNow.AddMinutes(-1), DateTimeOffset.UtcNow.AddDays(1));
        var raw = NativeProfileTemplates.Build(kind, "vpn.example.com", 443, "user", "abcdefghijklmnopqrstuvwxyz123456", kind == "openvpn-client" ? cert.ExportCertificatePem() : "");
        foreach (var content in new[] { raw, CustomProbeConfiguration.Build(raw, ECoreType.sing_box, 21512) }) {
            var file = Path.Combine(Path.GetTempPath(), "dicode-native-" + Guid.NewGuid() + ".json");
            await File.WriteAllTextAsync(file, content);
            try {
                var binary = Path.Combine(root!, "bin", "sing_box", "sing-box" + (OperatingSystem.IsWindows() ? ".exe" : ""));
                using var process = new System.Diagnostics.Process { StartInfo = new(binary) { UseShellExecute = false, RedirectStandardOutput = true, RedirectStandardError = true } };
                foreach (var arg in new[] { "check", "-c", file }) process.StartInfo.ArgumentList.Add(arg);
                process.Start(); var stdout = process.StandardOutput.ReadToEndAsync(); var stderr = process.StandardError.ReadToEndAsync();
                using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(20));
                try { await process.WaitForExitAsync(timeout.Token); } finally { if (!process.HasExited) process.Kill(true); }
                Assert.True(process.ExitCode == 0, await stderr + await stdout);
            } finally { File.Delete(file); }
        }
    }
}
