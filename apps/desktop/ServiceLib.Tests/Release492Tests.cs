using Xunit;

namespace ServiceLib.Tests;

public class Release492Tests
{
    [Fact]
    public async Task CopiedFoxLinkRecoversOnlyAnUnambiguousLocalAccount()
    {
        var previous = Environment.GetEnvironmentVariable("DICODE_DATA_DIR");
        var folder = Path.Combine(Path.GetTempPath(), Guid.NewGuid().ToString("N"));
        Environment.SetEnvironmentVariable("DICODE_DATA_DIR", folder);
        try
        {
            var link = new ProfileItem { ConfigType = EConfigType.SOCKS, Address = Global.Loopback, Port = FoxProfiles.LocalPort };
            Assert.Null(FoxProfiles.Read(await FoxProfiles.ResolveLocalAsync(link)));
            var account = new FoxAccount { Country = "DE", State = new JsonObject { ["access_token"] = "fixture" } };
            await FoxAccounts.SaveAsync(account, true);
            var restored = await FoxProfiles.ResolveLocalAsync(link);
            Assert.Equal(account.Id, FoxProfiles.Read(restored)?.AccountId);
            Assert.Null(FoxProfiles.Read(link)); // The stored/exported link is never overwritten.
            Assert.True(CoreManager.RequiresIsolatedProbe(ServiceLib.Tests.CoreConfig.CoreConfigTestFactory.CreateConfig(), new ServerTestItem { Profile = restored }));
            var remote = JsonUtils.DeepCopy(link); remote.Address = "192.0.2.1";
            Assert.Null(FoxProfiles.Read(await FoxProfiles.ResolveLocalAsync(remote)));
            var authenticated = JsonUtils.DeepCopy(link); authenticated.Username = "external";
            Assert.Null(FoxProfiles.Read(await FoxProfiles.ResolveLocalAsync(authenticated)));
            await FoxAccounts.SaveAsync(new FoxAccount(), true);
            Assert.Null(FoxProfiles.Read(await FoxProfiles.ResolveLocalAsync(link)));
        }
        finally
        {
            Environment.SetEnvironmentVariable("DICODE_DATA_DIR", previous);
            if (Directory.Exists(folder)) Directory.Delete(folder, true);
        }
    }
}
