using System.Text.Json;
using ServiceLib.Common;
using ServiceLib.Enums;
using ServiceLib.Handler;
using ServiceLib.Handler.Builder;
using ServiceLib.Handler.SysProxy;
using ServiceLib.Helper;
using ServiceLib.Manager;
using ServiceLib.Models.Configs;
using ServiceLib.Models.Entities;
using ServiceLib.Services;

if (args.Length == 0 || args.Contains("--help") || args[0] == "help")
{
    Console.WriteLine("""
        DicodePing CLI 4.5.0
        profiles                     List profile IDs, real latency and locations (JSON)
        import <file>                Import share links or native JSON configurations
        refresh                      Update enabled subscriptions
        ping                         Test real latency and sort successful profiles first
        connect [id | --best]         Run a profile until Ctrl+C; uses saved successful tests
        check <file> --engine xray|sing-box|mihomo
        run <file> --engine xray|sing-box|mihomo
        scan-cf <file>                Test supplied Cloudflare IPs with verified HTTPS
        --data <directory>           Separate writable data directory
        --tun                        Enable full-system TUN (requires administrator access)
        --system-proxy               Also set system proxy for this foreground session
        """);
    return 0;
}
if (args[0] is "--version" or "version") { Console.WriteLine("4.5.0"); return 0; }
string? Option(string name) { var i = Array.IndexOf(args, name); return i >= 0 && i+1 < args.Length ? args[i+1] : null; }
var data = Path.GetFullPath(Option("--data") ?? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "DicodePing-CLI"));
Directory.CreateDirectory(data);
Environment.SetEnvironmentVariable("DICODE_DATA_DIR", data);
using var cancellation = new CancellationTokenSource();
Console.CancelKeyPress += (_, e) => { e.Cancel = true; cancellation.Cancel(); };
try
{
    using var instance = new FileStream(Path.Combine(data, "cli.lock"), FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.None);
    if (args[0] is "run" or "check") return await NativeCommands.Execute(args, Option("--engine") ?? "xray", cancellation.Token);
    if (args[0] == "scan-cf") return await NativeCommands.Scan(args, cancellation.Token);
    if (!AppManager.Instance.InitApp()) throw new InvalidOperationException("Could not initialize configuration");
    var config = AppManager.Instance.Config;
    await ConfigHandler.InitBuiltinDNS(config);
    await ConfigHandler.InitBuiltinFullConfigTemplate(config);
    await ProfileExManager.Instance.Init();
    await BundledRuntimeInstaller.InstallAsync(Path.Combine(AppContext.BaseDirectory, "bin"), Utils.GetBinPath(""), "4.5.0");
    Task Output(bool success, string text) { Console.Error.WriteLine(text); return Task.CompletedTask; }
    await CoreManager.Instance.Init(config, Output);
    switch (args[0])
    {
        case "profiles":
            var extra = (await ProfileExManager.Instance.GetProfileExs()).ToDictionary(x => x.IndexId);
            Console.WriteLine(JsonSerializer.Serialize((await AppManager.Instance.ProfileModels("", "")).Select(p => new {
                id = p.IndexId, name = p.Remarks, type = p.ConfigType.ToString(),
                latency = extra.GetValueOrDefault(p.IndexId)?.Delay, location = extra.GetValueOrDefault(p.IndexId)?.IpInfo
            }), new JsonSerializerOptions { WriteIndented = true }));
            break;
        case "import":
            if (args.Length < 2) throw new ArgumentException("import requires a file");
            var imported = await ConfigHandler.AddBatchServers(config, await File.ReadAllTextAsync(args[1], cancellation.Token), "", false);
            if (imported <= 0) throw new InvalidDataException("No valid profiles in file");
            Console.WriteLine($"Imported {imported} profiles");
            break;
        case "refresh":
            await SubscriptionHandler.UpdateProcess(config, "", false, Output, cancellation.Token);
            break;
        case "ping":
            return await Ping(config, cancellation.Token);
        case "connect":
            var profiles = await AppManager.Instance.ProfileModels("", "");
            var selectedId = args.Length > 1 && !args[1].StartsWith("--") ? args[1] : config.IndexId;
            if (args.Contains("--best"))
            {
                var results = await ProfileExManager.Instance.GetProfileExs();
                var best = results.Where(x => x.Delay > 0 && profiles.Any(p => p.IndexId == x.IndexId)).OrderBy(x => x.Delay).FirstOrDefault();
                if (best is null) { await Ping(config, cancellation.Token); best = (await ProfileExManager.Instance.GetProfileExs()).Where(x => x.Delay > 0 && profiles.Any(p => p.IndexId == x.IndexId)).OrderBy(x => x.Delay).FirstOrDefault(); }
                selectedId = best?.IndexId ?? throw new InvalidOperationException("No server passed the real latency test");
            }
            var node = await AppManager.Instance.GetProfileItem(selectedId) ?? throw new InvalidOperationException("Select a profile ID or --best");
            if (args.Contains("--tun") && !Utils.IsAdministrator()) throw new InvalidOperationException("Run the CLI as administrator/root for --tun");
            config.TunModeItem.EnableTun = args.Contains("--tun");
            config.SystemProxyItem.SysProxyType = args.Contains("--system-proxy") ? ESysProxyType.ForcedChange : ESysProxyType.ForcedClear;
            var contexts = await CoreConfigContextBuilder.BuildAll(config, node);
            if (!contexts.Success) throw new InvalidOperationException("Profile validation failed");
            await CoreManager.Instance.LoadCore(contexts.MainResult.Context, contexts.PreSocksResult?.Context);
            if (!CoreManager.Instance.IsRunning) throw new InvalidOperationException("Core did not start");
            if (args.Contains("--system-proxy")) await SysProxyHandler.UpdateSysProxy(config, false);
            Console.Error.WriteLine($"Running {node.Remarks}. Press Ctrl+C to stop.");
            while (!cancellation.IsCancellationRequested && CoreManager.Instance.IsRunning) await Task.Delay(500, cancellation.Token);
            if (!cancellation.IsCancellationRequested) throw new IOException("Core stopped unexpectedly");
            break;
        default: throw new ArgumentException("Unknown command; use --help");
    }
    return 0;
}
catch (OperationCanceledException) when (cancellation.IsCancellationRequested) { return 130; }
catch (Exception error) { Console.Error.WriteLine(args.Contains("--verbose") ? error.ToString() : error.Message); return 1; }
finally
{
    await CoreManager.Instance.CoreStop();
    if (AppManager.Instance.Config is { } config && args.Contains("--system-proxy")) await SysProxyHandler.UpdateSysProxy(config, true);
}

static async Task<int> Ping(Config config, CancellationToken token)
{
    var profiles = new List<ProfileItem>();
    foreach (var model in await AppManager.Instance.ProfileModels("", ""))
        if (await AppManager.Instance.GetProfileItem(model.IndexId) is { } node) profiles.Add(node);
    var completed = new HashSet<string>();
    var service = new SpeedtestService(config, result => {
        lock (completed)
            if (!string.IsNullOrEmpty(result.IndexId) && int.TryParse(result.Delay, out var delay) && completed.Add(result.IndexId))
                Console.WriteLine(JsonSerializer.Serialize(new { id = result.IndexId, latency = delay, completed = completed.Count, total = profiles.Count }));
        if (result.Delay?.Length > 0 && !int.TryParse(result.Delay, out _)) Console.Error.WriteLine(result.Delay);
        if (result.Speed?.Length > 0) Console.Error.WriteLine(result.Speed);
        return Task.CompletedTask;
    });
    await service.RunLoop(ESpeedActionType.Realping, profiles, token);
    token.ThrowIfCancellationRequested();
    await ConfigHandler.SortServers(config, "", nameof(EServerColName.DelayVal), true);
    await ProfileExManager.Instance.SaveTo();
    var ids = profiles.Select(p => p.IndexId).ToHashSet();
    return (await ProfileExManager.Instance.GetProfileExs()).Any(p => ids.Contains(p.IndexId) && p.Delay > 0) ? 0 : 2;
}
