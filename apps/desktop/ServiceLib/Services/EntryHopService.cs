using System.Net.NetworkInformation;

namespace ServiceLib.Services;

/// <summary>Owns one managed entry hop and its verified local proxy; never substitutes a direct route.</summary>
public static class EntryHopService
{
    private static readonly SemaphoreSlim Gate = new(1, 1);
    private static ProcessService? _process;
    private static string _activeKey = "";
    private static bool _stopping;
    private static CancellationTokenSource? _health;
    public static event Func<Task>? Failed;
    public static string NetworkKey() => Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(string.Join("|",
        NetworkInterface.GetAllNetworkInterfaces().Where(x => x.OperationalStatus == OperationalStatus.Up)
            .Select(x => x.Id + ":" + string.Join(",", x.GetIPProperties().GatewayAddresses.Select(g => g.Address))).Order()))));

    public static IReadOnlyList<string> Candidates(EntryHopItem item) => item.Kind switch
    {
        "external" => ["external"],
        "psiphon" => ["psiphon-auto"],
        "aether-psiphon" => ["masque-h3", "masque-h2", "wireguard"],
        "aether-tor" => ["masque-h3", "masque-h2", "wireguard"],
        _ => ["masque-h3", "masque-h2", "wireguard", "gool-classic"],
    };

    public static async Task EnsureReadyAsync(CoreConfigContext context, CancellationToken token = default)
    {
        if (!context.UseEntryHop) return;
        await EnsureReadyAsync(context.AppConfig, false, token);
    }

    public static async Task EnsureReadyAsync(Config config, bool rescan = false, CancellationToken token = default)
    {
        await Gate.WaitAsync(token);
        try
        {
            var item = config.EntryHopItem;
            if (item.Port is < 1024 or > 65535) throw new InvalidOperationException("Invalid local proxy port");
            var network = NetworkKey();
            var key = $"{item.Kind}:{item.Port}:{network}";
            if (!rescan && key == _activeKey && _process is { HasExited: false }) return;
            await StopProcessAsync();
            if (item.Kind == "external")
            {
                await ProbeAsync(item.Port, config.SpeedTestItem.SpeedPingTestUrl, token);
                _activeKey = key;
                return;
            }
            // Never take over a port belonging to another program, nor count it as our helper.
            if (IPGlobalProperties.GetIPGlobalProperties().GetActiveTcpListeners().Any(x => x.Port == item.Port))
                throw new InvalidOperationException(ResUI.DicodeEntryPortBusy);
            var candidates = Candidates(item).ToList();
            if (!rescan && item.ConsecutiveFailures < item.RescanAfterFailures && item.NetworkKey == network && candidates.Remove(item.LastTransport)) candidates.Insert(0, item.LastTransport);
            var successes = new List<(string Transport, long Delay)>();
            using var overall = CancellationTokenSource.CreateLinkedTokenSource(token);
            overall.CancelAfter(TimeSpan.FromMinutes(3));
            foreach (var candidate in candidates)
            {
                overall.Token.ThrowIfCancellationRequested();
                try
                {
                    await StartAsync(item, candidate);
                    using var timeout = CancellationTokenSource.CreateLinkedTokenSource(overall.Token);
                    timeout.CancelAfter(TimeSpan.FromSeconds(40));
                    long delay = -1;
                    while (_process is { HasExited: false })
                    {
                        timeout.Token.ThrowIfCancellationRequested();
                        try { delay = await ProbeAsync(item.Port, config.SpeedTestItem.SpeedPingTestUrl, timeout.Token); break; }
                        catch (OperationCanceledException) when (timeout.IsCancellationRequested) { throw; }
                        catch { await Task.Delay(700, timeout.Token); }
                    }
                    if (delay < 0) throw new InvalidOperationException("Entry-hop process exited before readiness");
                    successes.Add((candidate, delay));
                    Logging.SaveLog($"Entry hop: {candidate} validated through SOCKS ({delay} ms)");
                    if (item.Policy != "best") break;
                }
                catch (OperationCanceledException) when (overall.IsCancellationRequested) { throw; }
                catch (Exception ex) { Logging.SaveLog($"Entry hop: {candidate} failed", ex); }
                await StopProcessAsync();
            }
            if (successes.Count == 0) { item.ConsecutiveFailures++; throw new InvalidOperationException(ResUI.DicodeEntryFailed); }
            var winner = successes.OrderBy(x => x.Delay).First().Transport;
            if (_process is null || _process.HasExited || successes.Last().Transport != winner)
            {
                await StopProcessAsync();
                await StartAsync(item, winner);
                using var ready = CancellationTokenSource.CreateLinkedTokenSource(overall.Token);
                ready.CancelAfter(TimeSpan.FromSeconds(40));
                while (true)
                {
                    try { await ProbeAsync(item.Port, config.SpeedTestItem.SpeedPingTestUrl, ready.Token); break; }
                    catch (OperationCanceledException) { throw; }
                    catch { await Task.Delay(700, ready.Token); }
                }
            }
            item.LastTransport = winner;
            item.NetworkKey = network;
            item.ConsecutiveFailures = 0;
            _activeKey = key;
            await ConfigHandler.SaveConfig(config);
            StartHealthMonitor(config, key);
        }
        catch { await StopProcessAsync(); throw; }
        finally { Gate.Release(); }
    }

    public static async Task<long> ProbeAsync(int port, string url, CancellationToken token)
    {
        using var handler = new HttpClientHandler { Proxy = new WebProxy($"socks5://127.0.0.1:{port}"), UseProxy = true, AllowAutoRedirect = false };
        using var client = new HttpClient(handler) { Timeout = TimeSpan.FromSeconds(8) };
        var watch = Stopwatch.StartNew();
        using var response = await client.GetAsync(url, HttpCompletionOption.ResponseHeadersRead, token);
        if (!response.IsSuccessStatusCode) throw new IOException("Entry-hop data-plane request failed");
        return Math.Max(1, watch.ElapsedMilliseconds);
    }

    private static async Task StartAsync(EntryHopItem item, string transport)
    {
        var directory = Utils.GetBinPath("", "aether");
        var binary = Path.Combine(directory, Utils.GetExeName("aether"));
        if (!File.Exists(binary)) throw new FileNotFoundException(ResUI.DicodeEntryFailed, binary);
        var listener = item.Kind == "psiphon" ? "--bind" : item.Kind == "aether-tor" ? "--tor-bind" : "--bind";
        var args = item.Kind == "psiphon" ? "--psiphon-only" : transport switch
        {
            "masque-h3" or "masque-h2" => "--masque",
            "gool-classic" => "--gool-classic",
            _ => "--wg"
        };
        if (item.Kind == "aether-psiphon") { args += " --psiphon"; listener = "--psiphon-bind"; }
        if (item.Kind == "aether-tor") args += " --tor";
        args += " --turbo -4 --quick-reconnect";
        args += $" {listener} 127.0.0.1:{item.Port} --config {Utils.GetConfigPath("aether-identity.json").AppendQuotes()}";
        var environment = new Dictionary<string, string> { ["AETHER_MASQUE_HTTP2"] = transport == "masque-h2" ? "1" : "0" };
        _process = new ProcessService(binary, args, directory, true, false, environment,
            (_, line) => { Logging.SaveLog("Entry hop: " + line); return Task.CompletedTask; });
        _process.Exited += exitCode => { if (!_stopping && _activeKey.IsNotEmpty()) { _activeKey = ""; if (Failed is { } failed) _ = failed(); } };
        await _process.StartAsync();
    }

    private static void StartHealthMonitor(Config config, string key)
    {
        _health?.Cancel(); _health?.Dispose();
        _health = new CancellationTokenSource();
        var token = _health.Token;
        _ = Task.Run(async () => {
            try
            {
                while (!token.IsCancellationRequested)
                {
                    await Task.Delay(TimeSpan.FromSeconds(30), token);
                    if (_activeKey != key) return;
                    var item = config.EntryHopItem;
                    var networkChanged = item.NetworkKey != NetworkKey();
                    if (!networkChanged)
                    {
                        try { await ProbeAsync(item.Port, config.SpeedTestItem.SpeedPingTestUrl, token); item.ConsecutiveFailures = 0; continue; }
                        catch (OperationCanceledException) { throw; }
                        catch (Exception ex) { Logging.SaveLog("Entry-hop health check", ex); item.ConsecutiveFailures++; }
                        if (item.ConsecutiveFailures < item.RescanAfterFailures) continue;
                    }
                    Logging.SaveLog(networkChanged ? "Entry-hop network changed; reconnecting without direct fallback" : "Entry-hop health failed; rescanning transports");
                    _activeKey = "";
                    await ConfigHandler.SaveConfig(config);
                    if (Failed is { } failed) await failed();
                    return;
                }
            }
            catch (OperationCanceledException) { }
            catch (Exception ex) { Logging.SaveLog("Entry-hop monitor", ex); }
        }, token);
    }

    private static async Task StopProcessAsync()
    {
        _health?.Cancel(); _health?.Dispose(); _health = null;
        _stopping = true;
        try { if (_process is not null) { await _process.StopAsync(); _process.Dispose(); _process = null; } _activeKey = ""; }
        finally { _stopping = false; }
    }
    public static async Task StopAsync() { await Gate.WaitAsync(); try { await StopProcessAsync(); } finally { Gate.Release(); } }
}
