using System.ComponentModel;
using Xunit;

namespace ServiceLib.Tests;
public class Release460Tests
{
    private static string Temporary() => Path.Combine(Path.GetTempPath(), "dicode-460-" + Guid.NewGuid().ToString("N"));
    private static byte[] Pe(ushort machine)
    {
        var bytes = new byte[256]; bytes[0] = 0x4d; bytes[1] = 0x5a; BitConverter.GetBytes(128).CopyTo(bytes, 60); bytes[128] = 0x50; bytes[129] = 0x45; BitConverter.GetBytes(machine).CopyTo(bytes, 132); return bytes;
    }
    [Theory]
    [InlineData(0x8664)] [InlineData(0x014c)] [InlineData(0xaa64)]
    public void ValidPeHeadersReportActualArchitecture(int machine)
    {
        var path = Temporary(); try { File.WriteAllBytes(path, Pe((ushort)machine)); Assert.Equal((ushort)machine, NativeLaunchPolicy.ReadWindowsMachine(path)); } finally { File.Delete(path); }
    }
    [Fact] public void PartialAndWrongPlatformBinariesFailBeforeLaunch()
    {
        var path = Temporary();
        try {
            foreach (var bytes in new[] { Array.Empty<byte>(), Encoding.UTF8.GetBytes("download failed"), new byte[64] }) { File.WriteAllBytes(path, bytes); Assert.Throws<InvalidDataException>(() => NativeLaunchPolicy.ReadWindowsMachine(path)); }
            var broken = Pe(0x8664); BitConverter.GetBytes(int.MaxValue).CopyTo(broken,60); File.WriteAllBytes(path,broken); Assert.Throws<InvalidDataException>(() => NativeLaunchPolicy.ReadWindowsMachine(path));
        } finally { File.Delete(path); }
    }
    [Fact] public void PermanentLoaderFailureIsCachedUntilExecutableIsRepaired()
    {
        var path = Temporary(); try {
            File.WriteAllBytes(path, Pe(0x8664)); Assert.False(NativeLaunchPolicy.RecordLoaderFailure(path, new Win32Exception(5)));
            Assert.True(NativeLaunchPolicy.RecordLoaderFailure(path, new Win32Exception(193)));
            Assert.Throws<InvalidOperationException>(() => NativeLaunchPolicy.Validate(path));
            File.SetLastWriteTimeUtc(path, DateTime.UtcNow.AddMinutes(1)); NativeLaunchPolicy.Validate(path);
        } finally { File.Delete(path); }
    }
    [Fact] public async Task OwnedUnstartedProcessCanBeStoppedWithoutReplacingStartupError()
    {
        using var process = new ProcessService("does-not-exist", "", Path.GetTempPath(), false, true, null, null, true);
        await process.StopAsync(); Assert.True(process.StopRequested);
    }
    [Fact] public async Task AccountVaultIsEncryptedAndDeletedAccountCannotBeResurrectedBySessionEvents()
    {
        var previous = Environment.GetEnvironmentVariable("DICODE_DATA_DIR"); var folder = Temporary(); Environment.SetEnvironmentVariable("DICODE_DATA_DIR", folder);
        try {
            var account = new FoxAccount { State = new JsonObject { ["email"] = "fixture@example.test", ["access_token"] = "private-session-sentinel" } };
            await FoxAccounts.SaveAsync(account, true); var cipher = File.ReadAllBytes(Path.Combine(FoxAccounts.Folder,"accounts.enc")); Assert.DoesNotContain("private-session-sentinel", Encoding.UTF8.GetString(cipher));
            Assert.Equal("private-session-sentinel", (await FoxAccounts.GetAsync(account.Id)).State["access_token"]!.ToString());
            if (!OperatingSystem.IsWindows()) Assert.Equal(UnixFileMode.UserRead | UnixFileMode.UserWrite, File.GetUnixFileMode(Path.Combine(FoxAccounts.Folder,"accounts.enc")));
            var tampered = cipher.ToArray(); tampered[^1] ^= 1; Assert.ThrowsAny<CryptographicException>(() => FoxAccounts.Decrypt(tampered));
            // Clear the vault to simulate local deletion while a child holds old state.
            File.Delete(Path.Combine(FoxAccounts.Folder,"accounts.enc")); await FoxAccounts.SaveAsync(account); Assert.Empty(await FoxAccounts.ListAsync());
        } finally { Environment.SetEnvironmentVariable("DICODE_DATA_DIR", previous); if (Directory.Exists(folder)) Directory.Delete(folder,true); }
    }
    [Fact] public void FoxProfileContainsNoCredentialsAndMalformedMetadataFailsClosed()
    {
        var path = Temporary(); try {
            var id = Guid.NewGuid().ToString("N"); var raw = FoxProfiles.Template(id,"DE",20001,20002); File.WriteAllText(path,raw);
            var node = new ProfileItem { ConfigType = EConfigType.Custom, Address = path }; Assert.Equal(new FoxProfile(id,"DE",20002), FoxProfiles.Read(node));
            Assert.DoesNotContain("access_token",raw); Assert.DoesNotContain("password",raw);
            File.WriteAllText(path,"{\"dicodeFox\":{\"accountId\":\"invalid\"}}"); Assert.Throws<FoxException>(() => FoxProfiles.Read(node));
        } finally { File.Delete(path); }
    }
}
