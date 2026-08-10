using System.Collections.Concurrent;
using System.Net.Sockets;
using System.Text.Json;
using System.Text.Json.Serialization;
using ServiceLib.Enums;
using ServiceLib.Handler;
using ServiceLib.Handler.Builder;
using ServiceLib.Handler.Fmt;
using ServiceLib.Handler.SysProxy;
using ServiceLib.Manager;
using ServiceLib.Models.Configs;
using ServiceLib.Models.Dto;
using ServiceLib.Models.Entities;
using ServiceLib.Services;

namespace DicodePing.CoreHost;

internal sealed class HostState
{
    private readonly Config _config;
    private readonly ConcurrentQueue<string> _logs = new();
    private readonly object _statsLock = new();
    private ServerSpeedItem _stats = new();
    private string? _connectedProfileId;

    public HostState(Config config) => _config = config;

    public async Task InitializeAsync()
    {
        _config.GuiItem.EnableStatistics = true;
        _config.GuiItem.DisplayRealTimeSpeed = true;
        _config.GuiItem.EnableLog = true;
        await ConfigHandler.InitBuiltinDNS(_config);
        await ConfigHandler.InitBuiltinRouting(_config);
        await ConfigHandler.InitBuiltinFullConfigTemplate(_config);
        await ProfileExManager.Instance.Init();
        await CoreManager.Instance.Init(_config, OnCoreUpdateAsync);
        await StatisticsManager.Instance.Init(_config, OnStatisticsAsync);
        await ConfigHandler.SaveConfig(_config);
        Log("runtime initialized");
    }

    public async Task<object> HandleAsync(string op, JsonElement args)
    {
        return op switch
        {
            "hello" => Hello(),
            "status" => await StatusAsync(),
            "sync_source" => await SyncSourceAsync(args),
            "list_profiles" => await ListProfilesAsync(args),
            "connect" => await ConnectAsync(args),
            "disconnect" => await DisconnectAsync(),
            "latency" => await LatencyAsync(args),
            "probe_payload" => await ProbePayloadAsync(args),
            "stats" => Stats(),
            "logs" => Logs(args),
            "settings_get" => SettingsGet(),
            "settings_set" => await SettingsSetAsync(args),
            "shutdown" => await ShutdownAsync(),
            _ => throw new InvalidOperationException($"unknown operation: {op}")
        };
    }

    private object Hello() => new
    {
        product = "dicodePing",
        protocol = 1,
        runtime = Environment.Version.ToString(),
        platform = Environment.OSVersion.Platform.ToString(),
        capabilities = new[] { "profiles", "system-proxy", "tun", "dns", "routing", "real-ping", "statistics", "logs" }
    };

    private async Task<object> SyncSourceAsync(JsonElement args)
    {
        var sourceId = RequireString(args, "source_id");
        var content = RequireString(args, "content");
        if (content.Length > 16 * 1024 * 1024)
            throw new InvalidOperationException("subscription payload is too large");

        var subId = StableSubId(sourceId);
        // AddBatchServers(..., isSub: true) owns replacement and preserves the
        // upstream runtime's matching active-profile/statistics behavior.
        var rc = await ConfigHandler.AddBatchServers(_config, content, subId, true);
        if (rc < 0)
            throw new InvalidOperationException("profile parser rejected the subscription payload");

        var profiles = await AppManager.Instance.ProfileItems(subId) ?? [];
        if (profiles.Count == 0)
            throw new InvalidOperationException("subscription did not contain supported proxy profiles");

        return new
        {
            source_id = sourceId,
            profile_count = profiles.Count,
            profiles = profiles.Select(ProfileDto).ToArray()
        };
    }

    private async Task<object> ListProfilesAsync(JsonElement args)
    {
        var sourceId = GetString(args, "source_id");
        var subId = string.IsNullOrWhiteSpace(sourceId) ? string.Empty : StableSubId(sourceId!);
        var profiles = await AppManager.Instance.ProfileItems(subId) ?? [];
        return new { profiles = profiles.Select(ProfileDto).ToArray() };
    }

    private async Task<object> ConnectAsync(JsonElement args)
    {
        var profileId = RequireString(args, "profile_id");
        var enableTun = GetBool(args, "tun", _config.TunModeItem.EnableTun);
        var systemProxy = GetString(args, "system_proxy") ?? "on";

        var profile = await AppManager.Instance.GetProfileItem(profileId)
            ?? throw new InvalidOperationException("profile not found");

        _config.TunModeItem.EnableTun = enableTun;
        _config.SystemProxyItem.SysProxyType = systemProxy.ToLowerInvariant() switch
        {
            "off" or "clear" => ESysProxyType.ForcedClear,
            "unchanged" => ESysProxyType.Unchanged,
            "pac" => ESysProxyType.Pac,
            _ => ESysProxyType.ForcedChange,
        };
        await ConfigHandler.SetDefaultServerIndex(_config, profileId);

        var built = await CoreConfigContextBuilder.BuildAll(_config, profile);
        if (!built.Success)
        {
            var errors = built.CombinedValidatorResult.Errors;
            throw new InvalidOperationException(errors.Count > 0 ? string.Join("; ", errors) : "profile validation failed");
        }

        await CoreManager.Instance.LoadCore(built.MainResult.Context, built.PreSocksResult?.Context);
        var port = AppManager.Instance.GetLocalPort(EInboundProtocol.socks);
        var open = await WaitForLocalPortAsync(port, TimeSpan.FromSeconds(8));
        if (!open)
        {
            await CoreManager.Instance.CoreStop();
            throw new InvalidOperationException("proxy core did not become ready before timeout");
        }

        if (!enableTun)
            await SysProxyHandler.UpdateSysProxy(_config, _config.SystemProxyItem.SysProxyType == ESysProxyType.ForcedClear);
        else
            await SysProxyHandler.UpdateSysProxy(_config, true);

        _connectedProfileId = profileId;
        Log($"connected {profile.Remarks} ({profile.Address}:{profile.Port})");
        return new
        {
            connected = true,
            profile = ProfileDto(profile),
            socks_port = port,
            tun = enableTun,
            system_proxy = _config.SystemProxyItem.SysProxyType.ToString()
        };
    }

    private async Task<object> DisconnectAsync()
    {
        await SysProxyHandler.UpdateSysProxy(_config, true);
        await CoreManager.Instance.CoreStop();
        _connectedProfileId = null;
        Log("disconnected");
        return new { connected = false };
    }

    private async Task<object> StatusAsync()
    {
        var port = AppManager.Instance.GetLocalPort(EInboundProtocol.socks);
        var running = _connectedProfileId is not null && await IsLocalPortOpenAsync(port, 350);
        if (!running)
            _connectedProfileId = null;
        return new
        {
            connected = running,
            profile_id = _connectedProfileId,
            socks_port = port,
            tun = _config.TunModeItem.EnableTun,
            system_proxy = _config.SystemProxyItem.SysProxyType.ToString(),
            running_core = AppManager.Instance.RunningCoreType.ToString()
        };
    }

    private async Task<object> LatencyAsync(JsonElement args)
    {
        if (!args.TryGetProperty("profile_ids", out var idsNode) || idsNode.ValueKind != JsonValueKind.Array)
            throw new InvalidOperationException("profile_ids must be an array");

        var ids = idsNode.EnumerateArray().Select(x => x.GetString()).Where(x => !string.IsNullOrWhiteSpace(x)).Select(x => x!).Distinct().Take(80).ToList();
        var profiles = await AppManager.Instance.GetProfileItemsByIndexIds(ids);
        if (profiles.Count == 0)
            return new { results = new Dictionary<string, int?>() };

        var results = await RunRealPingAsync(profiles);
        foreach (var id in ids)
            results.TryAdd(id, null);

        return new { results };
    }

    private async Task<object> ProbePayloadAsync(JsonElement args)
    {
        var content = RequireString(args, "content");
        if (content.Length > 16 * 1024 * 1024)
            throw new InvalidOperationException("probe payload is too large");

        var subId = "dp-scan-" + Guid.NewGuid().ToString("N");
        try
        {
            var rc = await ConfigHandler.AddBatchServers(_config, content, subId, true);
            if (rc < 1)
                return new { profiles = Array.Empty<object>() };
            var profiles = await AppManager.Instance.ProfileItems(subId) ?? [];
            var delays = await RunRealPingAsync(profiles);
            var rows = profiles.Select(p => new
            {
                profile = ProfileDto(p),
                ping_ms = delays.TryGetValue(p.IndexId, out var delay) ? delay : null,
            }).ToArray();
            return new { profiles = rows };
        }
        finally
        {
            await ConfigHandler.RemoveServersViaSubid(_config, subId, false);
        }
    }

    private async Task<ConcurrentDictionary<string, int?>> RunRealPingAsync(List<ProfileItem> profiles)
    {
        var results = new ConcurrentDictionary<string, int?>();
        var completed = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
        var speed = new SpeedtestService(_config, result =>
        {
            if (string.IsNullOrWhiteSpace(result.IndexId))
            {
                completed.TrySetResult(true);
            }
            else if (!string.IsNullOrWhiteSpace(result.Delay))
            {
                results[result.IndexId] = int.TryParse(result.Delay, out var value) && value > 0 ? value : null;
            }
            return Task.CompletedTask;
        });

        speed.RunLoop(ESpeedActionType.Realping, profiles);
        await Task.WhenAny(completed.Task, Task.Delay(TimeSpan.FromSeconds(Math.Min(90, 15 + profiles.Count * 2))));
        speed.ExitLoop();
        foreach (var profile in profiles)
            results.TryAdd(profile.IndexId, null);
        return results;
    }

    private object Stats()
    {
        lock (_statsLock)
        {
            return new
            {
                profile_id = _stats.IndexId,
                upload_bps = _stats.ProxyUp,
                download_bps = _stats.ProxyDown,
                today_upload = _stats.TodayUp,
                today_download = _stats.TodayDown,
                total_upload = _stats.TotalUp,
                total_download = _stats.TotalDown
            };
        }
    }

    private object Logs(JsonElement args)
    {
        var limit = Math.Clamp(GetInt(args, "limit", 200), 1, 1000);
        return new { lines = _logs.Reverse().Take(limit).Reverse().ToArray() };
    }

    private object SettingsGet() => new
    {
        tun = _config.TunModeItem.EnableTun,
        auto_route = _config.TunModeItem.AutoRoute,
        strict_route = _config.TunModeItem.StrictRoute,
        mtu = _config.TunModeItem.Mtu,
        system_proxy = _config.SystemProxyItem.SysProxyType.ToString(),
        dns_strategy = _config.RoutingBasicItem.DomainStrategy,
        dns_preference = _config.RoutingBasicItem.DomainStrategy4Singbox,
        log_enabled = _config.GuiItem.EnableLog,
    };

    private async Task<object> SettingsSetAsync(JsonElement args)
    {
        if (args.TryGetProperty("tun", out var tun) && tun.ValueKind is JsonValueKind.True or JsonValueKind.False)
            _config.TunModeItem.EnableTun = tun.GetBoolean();
        if (args.TryGetProperty("auto_route", out var ar) && ar.ValueKind is JsonValueKind.True or JsonValueKind.False)
            _config.TunModeItem.AutoRoute = ar.GetBoolean();
        if (args.TryGetProperty("strict_route", out var sr) && sr.ValueKind is JsonValueKind.True or JsonValueKind.False)
            _config.TunModeItem.StrictRoute = sr.GetBoolean();
        if (args.TryGetProperty("mtu", out var mtu) && mtu.TryGetInt32(out var mtuValue))
            _config.TunModeItem.Mtu = Math.Clamp(mtuValue, 1280, 9000);
        if (args.TryGetProperty("system_proxy", out var sp) && sp.ValueKind == JsonValueKind.String)
        {
            _config.SystemProxyItem.SysProxyType = (sp.GetString() ?? "on").ToLowerInvariant() switch
            {
                "off" or "clear" => ESysProxyType.ForcedClear,
                "unchanged" => ESysProxyType.Unchanged,
                "pac" => ESysProxyType.Pac,
                _ => ESysProxyType.ForcedChange,
            };
        }
        if (args.TryGetProperty("dns_strategy", out var ds) && ds.ValueKind == JsonValueKind.String)
        {
            var value = ds.GetString() ?? "AsIs";
            if (value is "AsIs" or "IPIfNonMatch" or "IPOnDemand")
                _config.RoutingBasicItem.DomainStrategy = value;
        }
        if (args.TryGetProperty("dns_preference", out var dp) && dp.ValueKind == JsonValueKind.String)
        {
            var value = dp.GetString() ?? string.Empty;
            if (value is "" or "prefer_ipv4" or "prefer_ipv6" or "ipv4_only" or "ipv6_only")
                _config.RoutingBasicItem.DomainStrategy4Singbox = value;
        }
        if (args.TryGetProperty("log_enabled", out var le) && le.ValueKind is JsonValueKind.True or JsonValueKind.False)
            _config.GuiItem.EnableLog = le.GetBoolean();

        await ConfigHandler.SaveConfig(_config);
        return SettingsGet();
    }

    private async Task<object> ShutdownAsync()
    {
        await SysProxyHandler.UpdateSysProxy(_config, true);
        await AppManager.Instance.AppExitAsync(false);
        _connectedProfileId = null;
        return new { shutdown = true };
    }

    private object ProfileDto(ProfileItem p) => new
    {
        id = p.IndexId,
        type = p.ConfigType.ToString(),
        name = string.IsNullOrWhiteSpace(p.Remarks) ? $"{p.ConfigType} {p.Address}" : p.Remarks,
        host = p.Address,
        port = p.Port,
        network = p.Network,
        security = p.StreamSecurity,
        source_id = p.Subid,
        share_uri = FmtHandler.GetShareUri(p) ?? string.Empty,
    };

    private Task OnCoreUpdateAsync(bool notify, string message)
    {
        if (!string.IsNullOrWhiteSpace(message)) Log(message);
        return Task.CompletedTask;
    }

    private Task OnStatisticsAsync(ServerSpeedItem item)
    {
        lock (_statsLock) _stats = item;
        return Task.CompletedTask;
    }

    private void Log(string message)
    {
        _logs.Enqueue($"{DateTimeOffset.Now:yyyy-MM-dd HH:mm:ss} {message}");
        while (_logs.Count > 1000) _logs.TryDequeue(out _);
    }

    private static string StableSubId(string sourceId)
    {
        var bytes = System.Security.Cryptography.SHA256.HashData(System.Text.Encoding.UTF8.GetBytes(sourceId));
        return "dp-" + Convert.ToHexString(bytes.AsSpan(0, 12)).ToLowerInvariant();
    }

    private static string RequireString(JsonElement args, string name)
    {
        var value = GetString(args, name);
        return string.IsNullOrWhiteSpace(value) ? throw new InvalidOperationException($"{name} is required") : value;
    }

    private static string? GetString(JsonElement args, string name) =>
        args.ValueKind == JsonValueKind.Object && args.TryGetProperty(name, out var node) && node.ValueKind == JsonValueKind.String ? node.GetString() : null;

    private static bool GetBool(JsonElement args, string name, bool fallback) =>
        args.ValueKind == JsonValueKind.Object && args.TryGetProperty(name, out var node) && node.ValueKind is JsonValueKind.True or JsonValueKind.False ? node.GetBoolean() : fallback;

    private static int GetInt(JsonElement args, string name, int fallback) =>
        args.ValueKind == JsonValueKind.Object && args.TryGetProperty(name, out var node) && node.TryGetInt32(out var value) ? value : fallback;

    private static async Task<bool> WaitForLocalPortAsync(int port, TimeSpan timeout)
    {
        var deadline = DateTime.UtcNow + timeout;
        while (DateTime.UtcNow < deadline)
        {
            if (await IsLocalPortOpenAsync(port, 300)) return true;
            await Task.Delay(150);
        }
        return false;
    }

    private static async Task<bool> IsLocalPortOpenAsync(int port, int timeoutMs)
    {
        try
        {
            using var client = new TcpClient();
            using var cts = new CancellationTokenSource(timeoutMs);
            await client.ConnectAsync("127.0.0.1", port, cts.Token);
            return true;
        }
        catch { return false; }
    }
}

internal static class Program
{
    private const string Prefix = "@dicodeping:";
    private static readonly JsonSerializerOptions Json = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
        WriteIndented = false,
    };

    public static async Task<int> Main()
    {
        try
        {
            if (!AppManager.Instance.InitApp() || !AppManager.Instance.InitComponents())
                throw new InvalidOperationException("failed to initialize runtime configuration");

            var state = new HostState(AppManager.Instance.Config);
            await state.InitializeAsync();
            Emit(new { type = "ready", ok = true });

            string? line;
            while ((line = await Console.In.ReadLineAsync()) is not null)
            {
                if (string.IsNullOrWhiteSpace(line)) continue;
                string? id = null;
                try
                {
                    using var doc = JsonDocument.Parse(line);
                    var root = doc.RootElement;
                    id = root.TryGetProperty("id", out var idNode) ? idNode.GetString() : null;
                    var op = root.TryGetProperty("op", out var opNode) ? opNode.GetString() : null;
                    if (string.IsNullOrWhiteSpace(op)) throw new InvalidOperationException("op is required");
                    var args = root.TryGetProperty("args", out var argsNode) ? argsNode : default;
                    var result = await state.HandleAsync(op!, args);
                    Emit(new { id, ok = true, result });
                    if (op == "shutdown") break;
                }
                catch (Exception ex)
                {
                    Emit(new { id, ok = false, error = ex.Message, error_type = ex.GetType().Name });
                }
            }

            await AppManager.Instance.AppExitAsync(false);
            return 0;
        }
        catch (Exception ex)
        {
            Emit(new { type = "fatal", ok = false, error = ex.Message });
            return 2;
        }
    }

    private static void Emit(object payload)
    {
        Console.Out.WriteLine(Prefix + JsonSerializer.Serialize(payload, Json));
        Console.Out.Flush();
    }
}
