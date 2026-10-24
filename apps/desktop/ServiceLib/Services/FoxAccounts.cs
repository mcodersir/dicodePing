using System.Security.Cryptography;

namespace ServiceLib.Services;

public sealed class FoxException(string code, string message) : Exception(message)
{
    public string Code { get; } = code;
}
public sealed class FoxAccount
{
    public string Id { get; set; } = Guid.NewGuid().ToString("N");
    public string Country { get; set; } = "REC";
    public JsonObject State { get; set; } = new();
    public JsonObject Info { get; set; } = new();
    public string Email => State["email"]?.ToString() ?? "";
    public bool Pending => State["session_token"]?.ToString().IsNotEmpty() == true;
    public override string ToString() => $"{Email} · {Country}";
}

/// <summary>Passwords never enter this vault. DPAPI on Windows, owner-only AES-GCM elsewhere.</summary>
public static class FoxAccounts
{
    private static readonly SemaphoreSlim Gate = new(1, 1);
    public static string Folder => Path.Combine(Environment.GetEnvironmentVariable("DICODE_DATA_DIR") ?? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "DicodePing"), "FoxAccounts");
    private static string FileName => Path.Combine(Folder, "accounts.enc");
    private static void Prepare()
    {
        Directory.CreateDirectory(Folder);
        if (!OperatingSystem.IsWindows()) File.SetUnixFileMode(Folder, UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.UserExecute);
    }
    private static byte[] Key()
    {
        var path = Path.Combine(Folder, "vault.key");
        if (!File.Exists(path)) { using var file = new FileStream(path, FileMode.CreateNew, FileAccess.Write, FileShare.None); file.Write(RandomNumberGenerator.GetBytes(32)); }
        if (!OperatingSystem.IsWindows()) File.SetUnixFileMode(path, UnixFileMode.UserRead | UnixFileMode.UserWrite);
        return File.ReadAllBytes(path);
    }
    public static byte[] Encrypt(byte[] clear)
    {
        Prepare();
        if (OperatingSystem.IsWindows()) return new byte[] { 1 }.Concat(ProtectedData.Protect(clear, null, DataProtectionScope.CurrentUser)).ToArray();
        var nonce = RandomNumberGenerator.GetBytes(12); var tag = new byte[16]; var encrypted = new byte[clear.Length];
        using var aes = new AesGcm(Key(), 16); aes.Encrypt(nonce, clear, encrypted, tag);
        return new byte[] { 2 }.Concat(nonce).Concat(tag).Concat(encrypted).ToArray();
    }
    public static byte[] Decrypt(byte[] data)
    {
        Prepare();
        if (data.Length > 1 && data[0] == 1 && OperatingSystem.IsWindows()) return ProtectedData.Unprotect(data[1..], null, DataProtectionScope.CurrentUser);
        if (data.Length < 29 || data[0] != 2) throw new CryptographicException("Unsupported account vault");
        var clear = new byte[data.Length - 29]; using var aes = new AesGcm(Key(), 16); aes.Decrypt(data.AsSpan(1,12), data.AsSpan(29), data.AsSpan(13,16), clear); return clear;
    }
    private static List<FoxAccount> Read()
    {
        if (!File.Exists(FileName)) return [];
        var clear = Decrypt(File.ReadAllBytes(FileName));
        try { return JsonSerializer.Deserialize<List<FoxAccount>>(clear) ?? []; }
        finally { CryptographicOperations.ZeroMemory(clear); }
    }
    private static async Task WriteAsync(List<FoxAccount> all)
    {
        var temporary = FileName + "." + Guid.NewGuid().ToString("N") + ".tmp";
        var clear = JsonSerializer.SerializeToUtf8Bytes(all);
        try { await File.WriteAllBytesAsync(temporary, Encrypt(clear)); if (!OperatingSystem.IsWindows()) File.SetUnixFileMode(temporary, UnixFileMode.UserRead | UnixFileMode.UserWrite); File.Move(temporary, FileName, true); }
        finally { CryptographicOperations.ZeroMemory(clear); if (File.Exists(temporary)) File.Delete(temporary); }
    }
    public static async Task<List<FoxAccount>> ListAsync()
    {
        await Gate.WaitAsync(); try { return Read(); } finally { Gate.Release(); }
    }
    public static async Task SaveAsync(FoxAccount account, bool create = false)
    {
        await Gate.WaitAsync();
        try {
            var all = Read(); if (!create && !all.Any(x => x.Id == account.Id)) return; all.RemoveAll(x => x.Id == account.Id); all.Add(account);
            await WriteAsync(all);
        } finally { Gate.Release(); }
    }
    private static async Task UpdateSessionAsync(string id, JsonObject state, JsonObject? info = null)
    {
        await Gate.WaitAsync();
        try {
            var all = Read(); var current = all.FirstOrDefault(a => a.Id == id); if (current is null) return;
            current.State = state.DeepClone().AsObject(); if (info is not null) current.Info = info.DeepClone().AsObject(); await WriteAsync(all);
        } finally { Gate.Release(); }
    }
    private static async Task UpdateQuotaAsync(string id, JsonObject info)
    {
        await Gate.WaitAsync();
        try {
            var all = Read(); var account = all.FirstOrDefault(a => a.Id == id);
            if (account is null) return;
            account.Info = info.DeepClone().AsObject(); await WriteAsync(all);
        } finally { Gate.Release(); }
        await FoxProfiles.UpdateQuotaAsync(await GetAsync(id));
    }
    public static async Task RemoveAsync(string id)
    {
        await Gate.WaitAsync();
        try { var all = Read(); all.RemoveAll(x => x.Id == id); await WriteAsync(all); }
        finally { Gate.Release(); }
        foreach (var sub in (await AppManager.Instance.SubItems()).Where(s => s.Url == "dicode-fox://" + id)) await ConfigHandler.DeleteSubItem(AppManager.Instance.Config, sub.Id);
    }
    public static async Task<FoxAccount> GetAsync(string id) => (await ListAsync()).FirstOrDefault(x => x.Id == id) ?? throw new FoxException("login_required", "Sign in to the Fox account for this profile");
    private static ProcessService Helper()
    {
        var path = Utils.GetBinPath(Utils.GetExeName("dicode-fox"), "fox");
        if (!File.Exists(path)) throw new FoxException("missing_helper", "Fox helper is missing; install the complete DicodePing package");
        return new ProcessService(path, "", Path.GetDirectoryName(path)!, false, true, null, null, privateProtocol: true);
    }
    public static async Task<JsonObject> RequestAsync(JsonObject request, CancellationToken token = default)
    {
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(token); timeout.CancelAfter(TimeSpan.FromSeconds(100));
        using var process = Helper();
        try { return await process.StartPrivateProtocolAsync(request, null, timeout.Token); }
        finally { await process.StopAsync(); }
    }
    public static async Task<FoxAccount> LoginAsync(string email, string password, CancellationToken token)
    {
        var result = await RequestAsync(new JsonObject { ["operation"] = "login", ["email"] = email.Trim(), ["password"] = password }, token);
        var account = (await ListAsync()).FirstOrDefault(a => string.Equals(a.Email, email.Trim(), StringComparison.OrdinalIgnoreCase)) ?? new FoxAccount();
        account.State = (result["state"] as JsonObject)?.DeepClone().AsObject() ?? throw new FoxException("provider", "No account session returned");
        await SaveAsync(account, create: true); if (!account.Pending) return await RefreshAsync(account.Id, true, token); return account;
    }
    public static async Task<FoxAccount> VerifyAsync(string id, string code, CancellationToken token)
    {
        var account = await GetAsync(id); var result = await RequestAsync(new JsonObject { ["operation"] = "verify", ["code"] = code, ["state"] = account.State.DeepClone() }, token);
        account.State = result["state"]!.DeepClone().AsObject(); await SaveAsync(account); return await RefreshAsync(id, true, token);
    }
    public static async Task<FoxAccount> RefreshAsync(string id, bool addProfile, CancellationToken token = default)
    {
        var account = await GetAsync(id); var result = await RequestAsync(new JsonObject { ["operation"] = "status", ["state"] = account.State.DeepClone() }, token);
        account.State = result["state"]!.DeepClone().AsObject(); account.Info = result["account"]?.DeepClone().AsObject() ?? new JsonObject(); await SaveAsync(account);
        if (addProfile) await FoxProfiles.SyncAsync(await GetAsync(id));
        return account;
    }
    public static async Task<ProcessService> StartProxyAsync(string id, string country, int port, CancellationToken token = default, string? bindInterface = null)
    {
        var account = await GetAsync(id); var process = Helper();
        try {
            var result = await process.StartPrivateProtocolAsync(new JsonObject { ["operation"] = "serve", ["bind_interface"] = bindInterface.NullIfEmpty() ?? PhysicalUplink.Find(), ["state"] = account.State.DeepClone(), ["country"] = country, ["listen"] = $"127.0.0.1:{port}" }, async message => {
                if (message["event"]?.ToString() == "state" && message["state"] is JsonObject state) { await UpdateSessionAsync(id, state); }
                if (message["event"]?.ToString() == "quota" && message["account"] is JsonObject info) await UpdateQuotaAsync(id, info);
            }, token);
            await UpdateSessionAsync(id, result["state"]!.AsObject(), result["account"] as JsonObject);
            await FoxProfiles.UpdateQuotaAsync(await GetAsync(id));
            return process;
        } catch { await process.StopAsync(); process.Dispose(); throw; }
    }
}

public record FoxProfile(string AccountId, string Country, int HelperPort);
public static class FoxProfiles
{
    public const int LocalPort = 7854;
    public const string ShareUri = "socks5://127.0.0.1:7854#Firefox-VPN";
    public static FoxProfile? Read(ProfileItem? node)
    {
        if (node is null) return null;
        if (node.ConfigType == EConfigType.SOCKS && node.GetProtocolExtra().FoxAccountId is { } accountId) {
            var country = node.GetProtocolExtra().FoxCountry ?? "REC";
            if (!Guid.TryParseExact(accountId, "N", out _) || node.Address != Global.Loopback || node.Port != LocalPort
                || !(country == "REC" || (country.Length == 2 && country.All(char.IsAsciiLetter))))
                throw new FoxException("input", "Invalid managed Fox SOCKS profile");
            return new FoxProfile(accountId, country.ToUpperInvariant(), LocalPort);
        }
        if (node.ConfigType != EConfigType.Custom) return null;
        var path = File.Exists(node.Address) ? node.Address : Utils.GetConfigPath(node.Address);
        if (!File.Exists(path)) return null;
        try {
            var fox = JsonNode.Parse(File.ReadAllText(path))?["dicodeFox"];
            if (fox is null) return null;
            var id = fox["accountId"]?.ToString(); var country = fox["country"]?.ToString() ?? "REC";
            if (!Guid.TryParseExact(id, "N", out _) || !(country == "REC" || (country.Length == 2 && country.All(char.IsAsciiLetter))) || fox["helperPort"] is not JsonValue port || !port.TryGetValue<int>(out var number) || number is < 1 or > 65535)
                throw new FoxException("input", "Invalid Fox profile metadata; recreate this profile from the Fox page");
            return new FoxProfile(id!, country.ToUpperInvariant(), number);
        }
        catch (JsonException) { return null; }
    }
    // A copied localhost link has no account metadata. Recover it only when its
    // subscription identifies the account, or there is exactly one local account.
    public static async Task<ProfileItem> ResolveLocalAsync(ProfileItem node)
    {
        if (Read(node) is not null || node.ConfigType != EConfigType.SOCKS
            || node.Address != Global.Loopback || node.Port != LocalPort
            || node.Username.IsNotEmpty() || node.Password.IsNotEmpty()) return node;
        var accounts = (await FoxAccounts.ListAsync()).Where(a => !a.Pending).ToList();
        var sub = node.Subid.IsNullOrEmpty() ? null : await AppManager.Instance.GetSubItem(node.Subid);
        var account = accounts.FirstOrDefault(a => sub?.Url == "dicode-fox://" + a.Id)
            ?? (accounts.Count == 1 ? accounts[0] : null);
        if (account is null) return node; // An external SOCKS listener remains external.
        var resolved = JsonUtils.DeepCopy(node);
        resolved.SetProtocolExtra(resolved.GetProtocolExtra() with { FoxAccountId = account.Id, FoxCountry = account.Country });
        return resolved;
    }

    public static ProfileItem ForConnection(ProfileItem node)
    {
        if (Read(node) is not { } fox) return node;
        var runtime = JsonUtils.DeepCopy(node);
        runtime.ConfigType = EConfigType.SOCKS; runtime.CoreType = ECoreType.Xray;
        runtime.Address = Global.Loopback; runtime.Port = LocalPort; runtime.PreSocksPort = null;
        runtime.Username = runtime.Password = runtime.StreamSecurity = runtime.Network = string.Empty;
        runtime.SetProtocolExtra(new ProtocolExtraItem { FoxAccountId = fox.AccountId, FoxCountry = fox.Country });
        return runtime;
    }
    public static string Template(string id, string country, int privatePort, int helperPort) => new JsonObject {
        ["dicodeFox"] = new JsonObject { ["accountId"] = id, ["country"] = country, ["helperPort"] = helperPort },
        ["log"] = new JsonObject { ["loglevel"] = "warning" },
        ["inbounds"] = new JsonArray(new JsonObject { ["tag"] = "socks", ["listen"] = "127.0.0.1", ["port"] = privatePort, ["protocol"] = "socks", ["settings"] = new JsonObject { ["auth"] = "noauth", ["udp"] = true } }),
        ["outbounds"] = new JsonArray(new JsonObject { ["tag"] = "proxy", ["protocol"] = "socks", ["settings"] = new JsonObject { ["servers"] = new JsonArray(new JsonObject { ["address"] = "127.0.0.1", ["port"] = helperPort }) } }, new JsonObject { ["tag"] = "block", ["protocol"] = "blackhole" }),
        ["routing"] = new JsonObject { ["rules"] = new JsonArray(new JsonObject { ["type"] = "field", ["network"] = "udp", ["port"] = "443", ["outboundTag"] = "block" }) }
    }.ToJsonString();
    public static async Task UpdateQuotaAsync(FoxAccount account)
    {
        var sub = (await AppManager.Instance.SubItems()).FirstOrDefault(s => s.Url == "dicode-fox://" + account.Id);
        if (sub is null) return;
        ApplyQuota(sub, account);
        await ConfigHandler.AddSubItem(AppManager.Instance.Config, sub);
        AppEvents.FoxQuotaUpdated.Publish(RxVoid.Default);
    }
    private static void ApplyQuota(SubItem sub, FoxAccount account)
    {
        sub.TotalBytes = account.Info["quota_max"]?.GetValue<long>() ?? 0;
        var remaining = account.Info["quota_remaining"]?.GetValue<long>();
        sub.UploadBytes = 0;
        sub.DownloadBytes = remaining is not null && sub.TotalBytes > 0 ? Math.Clamp(sub.TotalBytes - remaining.Value, 0, sub.TotalBytes) : 0;
        sub.UpdateTime = DateTimeOffset.UtcNow.ToUnixTimeSeconds();
    }
    public static async Task SyncAsync(FoxAccount account)
    {
        var config = AppManager.Instance.Config; var sub = (await AppManager.Instance.SubItems()).FirstOrDefault(s => s.Url == "dicode-fox://" + account.Id)
            ?? new SubItem { Id = Guid.NewGuid().ToString("N"), Url = "dicode-fox://" + account.Id, Remarks = ResUI.DicodeFoxTitle + " · " + account.Email, AutoUpdateInterval = 0 };
        ApplyQuota(sub, account); await ConfigHandler.AddSubItem(config, sub);
        var nodes = await AppManager.Instance.ProfileItems(sub.Id) ?? []; var existing = nodes.FirstOrDefault();
        var node = new ProfileItem { IndexId = existing?.IndexId ?? "", ConfigType = EConfigType.SOCKS, CoreType = ECoreType.Xray,
            Remarks = ResUI.DicodeFoxTitle + " · Firefox VPN · " + account.Country, Address = Global.Loopback, Port = LocalPort,
            DisplayLog = true, Subid = sub.Id, IsSub = true };
        node.SetProtocolExtra(new ProtocolExtraItem { FoxAccountId = account.Id, FoxCountry = account.Country });
        if (await ConfigHandler.AddSocksServer(config, node) != 0) throw new IOException("Could not save Fox SOCKS profile");
        foreach (var duplicate in nodes.Skip(1)) await ConfigHandler.RemoveServers(config, [duplicate]);
    }
}
