namespace ServiceLib.Manager;

/// <summary>
/// Core process processing class
/// </summary>
public class CoreManager
{
    private static readonly Lazy<CoreManager> _instance = new(() => new());
    public static CoreManager Instance => _instance.Value;
    private Config _config;

    [SupportedOSPlatform("windows")]
    private WindowsJobService? _processJob;

    private ProcessService? _processService;
    private ProcessService? _processPreService;
    private ProcessService? _foxProcess;
    private string? _activeConfigHash;
    private int _intentionalStopDepth;
    private bool _linuxSudo = false;
    private Func<bool, string, Task>? _updateFunc;
    private readonly SemaphoreSlim _lifecycleGate = new(1, 1);
    public long SessionId { get; private set; }
    public string? ActiveProfileId { get; private set; }
    public int StatisticsPort { get; private set; }
    public int ActiveLocalPort { get; private set; }
    public int RequestedLocalPort { get; private set; }
    private readonly SemaphoreSlim _probeLaunchLock = new(1, 1);
    private const string _tag = "CoreHandler";

    public string? LastStartupError { get; private set; }
    private bool _chainReady;
    private volatile bool _trafficVerified;
    public bool IsTrafficVerified => _trafficVerified && IsRunning;
    public bool IsRunning => _chainReady && _processService is { HasExited: false }
        && (_processPreService is null || !_processPreService.HasExited)
        && (_foxProcess is null || !_foxProcess.HasExited);
    public event Func<int, Task>? UnexpectedExit;

    public async Task<bool> VerifyTrafficAsync(CancellationToken token = default)
    {
        if (!IsRunning) return false;
        var session = SessionId;
        var proxy = ConnectionHandler.CreateActiveProxy();
        var delay = await ConnectionHandler.GetRealPingTime(proxy, token);
        if (!IsRunning || session != SessionId) return false;
        _trafficVerified = delay > 0;
        return _trafficVerified;
    }

    public async Task Init(Config config, Func<bool, string, Task> updateFunc)
    {
        _config = config;
        _updateFunc = updateFunc;

        //Copy the bin folder to the storage location (for init)
        if (Environment.GetEnvironmentVariable(Global.LocalAppData) == "1")
        {
            var fromPath = Utils.GetBaseDirectory("bin");
            var toPath = Utils.GetBinPath("");
            if (fromPath != toPath)
            {
                await BundledRuntimeInstaller.InstallAsync(fromPath, toPath, Utils.GetVersionInfo());
            }
        }

        if (Utils.IsNonWindows())
        {
            var coreInfo = CoreInfoManager.Instance.GetCoreInfo();
            foreach (var it in coreInfo)
            {
                if (it.CoreType == ECoreType.v2rayN)
                {
                    if (Utils.UpgradeAppExists(out var upgradeFileName))
                    {
                        await Utils.SetLinuxChmod(upgradeFileName);
                    }
                    continue;
                }

                foreach (var name in it.CoreExes)
                {
                    var exe = Utils.GetBinPath(Utils.GetExeName(name), it.CoreType.ToString());
                    if (File.Exists(exe))
                    {
                        await Utils.SetLinuxChmod(exe);
                    }
                }
            }
        }
    }

    /// <param name="mainContext">Resolved main context (with pre-socks ports already merged if applicable).</param>
    /// <param name="preContext">Optional pre-socks context passed to <see cref="CoreStartPreService"/>.</param>
    public async Task LoadCore(CoreConfigContext? mainContext, CoreConfigContext? preContext)
    {
        await _lifecycleGate.WaitAsync();
        try { await LoadCoreExclusive(mainContext, preContext); }
        finally { _lifecycleGate.Release(); }
    }

    private async Task LoadCoreExclusive(CoreConfigContext? mainContext, CoreConfigContext? preContext)
    {
        if (mainContext == null)
        {
            await UpdateFunc(false, ResUI.CheckServerSettings);
            return;
        }

        var node = mainContext.Node;
        var fileName = Utils.GetBinConfigPath(Global.CoreConfigFileName);
        var result = await CoreConfigHandler.GenerateClientConfig(mainContext, fileName);
        if (result.Success != true)
        {
            await UpdateFunc(true, result.Msg);
            return;
        }

        var preFileName = Utils.GetBinConfigPath(Global.CorePreConfigFileName);
        if (preContext is not null) {
            var preResult = await CoreConfigHandler.GenerateClientConfig(preContext, preFileName);
            if (!preResult.Success) throw new IOException(preResult.Msg ?? "Could not generate the TUN bridge configuration");
        }
        var preJson = preContext is null ? "" : await File.ReadAllTextAsync(preFileName);
        var fox = FoxProfiles.Read(mainContext.Node);
        var generatedConfigHash = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(
            await File.ReadAllTextAsync(fileName) + "|bridge:" + preJson + (fox is null ? "" : $"|fox:{fox.AccountId}:{fox.Country}"))));
        if (IsRunning && string.Equals(_activeConfigHash, generatedConfigHash, StringComparison.Ordinal))
        {
            Logging.SaveLog("CoreHandler: identical generated configuration; keeping the active TUN process.");
            return;
        }

        await UpdateFunc(false, $"{node.GetSummary()}");
        await UpdateFunc(false, $"{Utils.GetRuntimeInfo()}");
        await UpdateFunc(false, string.Format(ResUI.StartService, DateTime.Now.ToString("yyyy/MM/dd HH:mm:ss")));
        await CoreStopExclusive(keepEntryHop: true);
        try {
        await EntryHopService.EnsureReadyAsync(mainContext);
        await Task.Delay(250);

        if (fox is not null) {
            using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(100));
            var helper = await FoxAccounts.StartProxyAsync(fox.AccountId, fox.Country, fox.HelperPort, timeout.Token, mainContext.AppConfig.CoreBasicItem.BindInterface);
            _foxProcess = helper;
            helper.Exited += code => { if (ReferenceEquals(_foxProcess, helper) && !helper.StopRequested && Volatile.Read(ref _intentionalStopDepth) == 0) _ = StopAfterBridgeFailureAsync(code, helper); };
        }
        // A SOCKS inbound can start even when its localhost upstream is absent.
        // Refuse that broken chain before claiming a running tunnel.
        if (node.ConfigType == EConfigType.SOCKS && IPAddress.TryParse(node.Address, out var address) && IPAddress.IsLoopback(address)) {
            using var upstream = new TcpClient();
            using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(3));
            try { await upstream.ConnectAsync(address, node.Port, deadline.Token); }
            catch (Exception error) { throw new IOException(string.Format(ResUI.DicodeLocalSocksMissing, node.Address, node.Port), error); }
        }
        await CoreStart(mainContext);
        if (_processService is null) { await CoreStopExclusive(); return; }
        if (_foxProcess is { HasExited: true }) { await CoreStopExclusive(); throw new FoxException("helper", "Firefox proxy stopped during startup"); }
        await WaitForProxyPort(preContext);
        await CoreStartPreService(preContext);

        AppManager.Instance.RunningCoreType = mainContext.Node.ConfigType == EConfigType.Custom
            ? preContext?.RunCoreType ?? mainContext.RunCoreType : mainContext.RunCoreType;

        if (_processService != null)
        {
            _activeConfigHash = generatedConfigHash;
            StatisticsPort = AppManager.Instance.RunningCoreType == ECoreType.sing_box
                ? AppManager.Instance.GetStatePort2(mainContext.AppConfig.TunModeItem.EnableTun) : AppManager.Instance.StatePort;
            ActiveProfileId = mainContext.AppConfig.IndexId.NullIfEmpty() ?? mainContext.Node.IndexId;
            ActiveLocalPort = mainContext.AppConfig.Inbound.First(i => i.Protocol == nameof(EInboundProtocol.socks)).LocalPort;
            RequestedLocalPort = mainContext.RequestedLocalPort;
            SessionId++;
            _chainReady = true;
            await UpdateFunc(true, $"{node.GetSummary()}");
        }
        } catch { await CoreStopExclusive(); throw; }
    }

    public async Task<ProcessService?> LoadCoreConfigSpeedtest(List<ServerTestItem> selecteds)
    {
        await _probeLaunchLock.WaitAsync();
        try { return await ReadyProbe(await StartProbeBatch(selecteds), selecteds.Where(x => x.AllowTest).Select(x => x.Port)); }
        finally { _probeLaunchLock.Release(); }
    }

    public async Task<ProcessService?> LoadCoreConfigSpeedtest(ServerTestItem item, CancellationToken token = default)
    {
        await _probeLaunchLock.WaitAsync(token);
        try { return await ReadyProbe(await StartProbeItem(item, token), [item.Port], token); }
        finally { _probeLaunchLock.Release(); }
    }

    private static async Task<ProcessService?> ReadyProbe(ProcessService? process, IEnumerable<int> ports, CancellationToken token = default)
    {
        if (process is null) return null;
        var portList = ports.ToList();
        try
        {
            foreach (var port in portList)
            {
                var ready = false;
                for (var attempt = 0; attempt < 100 && !process.HasExited; attempt++)
                {
                    token.ThrowIfCancellationRequested();
                    try
                    {
                        using var client = new TcpClient();
                        using var deadline = CancellationTokenSource.CreateLinkedTokenSource(token);
                        deadline.CancelAfter(TimeSpan.FromMilliseconds(150));
                        await client.ConnectAsync(Global.Loopback, port, deadline.Token);
                        ready = true; break;
                    }
                    catch (OperationCanceledException) when (token.IsCancellationRequested) { throw; }
                    catch (Exception) { await Task.Delay(50, token); }
                }
                if (!ready) { await process.StopAsync(); process.Dispose(); return null; }
            }
            return process;
        }
        catch { await process.StopAsync(); process.Dispose(); throw; }
    }

    public static bool RequiresIsolatedProbe(Config config, ServerTestItem item) =>
        item.ConfigType == EConfigType.Custom || FoxProfiles.Read(item.Profile) is not null || config.EntryHopItem.Applies(item.Profile);

    private async Task<ProcessService?> StartProbeBatch(List<ServerTestItem> selecteds)
    {
        if (selecteds.Any(x => RequiresIsolatedProbe(_config, x))) return null;
        var coreType = selecteds.FirstOrDefault()?.CoreType == ECoreType.sing_box ? ECoreType.sing_box : ECoreType.Xray;
        var fileName = string.Format(Global.CoreSpeedtestConfigFileName, Utils.GetGuid(false));
        var configPath = Utils.GetBinConfigPath(fileName);
        var result = await CoreConfigHandler.GenerateClientSpeedtestConfig(_config, configPath, selecteds, coreType);
        await UpdateFunc(false, result.Msg);
        if (result.Success != true)
        {
            return null;
        }

        await UpdateFunc(false, string.Format(ResUI.StartService, DateTime.Now.ToString("yyyy/MM/dd HH:mm:ss")));
        await UpdateFunc(false, configPath);

        var coreInfo = CoreInfoManager.Instance.GetCoreInfo(coreType);
        var process = await RunProcess(coreInfo, fileName, true, false);
        if (process is not null) process.TemporaryConfigPath = configPath;
        else if (File.Exists(configPath)) File.Delete(configPath);
        return process;
    }

    private async Task<ProcessService?> StartProbeItem(ServerTestItem testItem, CancellationToken token)
    {
        // An isolated test owns its inbound/helper port, never the active profile's 7854 or remote server port.
        testItem.Port = Utils.GetFreePort(AppManager.Instance.GetLocalPort(EInboundProtocol.speedtest) + testItem.QueueNum);
        var node = testItem.Profile;
        if (node is null)
        {
            return null;
        }

        if (FoxProfiles.Read(node) is { } fox)
            return await FoxAccounts.StartProxyAsync(fox.AccountId, fox.Country, testItem.Port, token);
        var fileName = string.Format(Global.CoreSpeedtestConfigFileName, Utils.GetGuid(false));
        var configPath = Utils.GetBinConfigPath(fileName);
        var (context, _) = await CoreConfigContextBuilder.Build(_config, node);
        await EntryHopService.EnsureReadyAsync(context, token);
        var result = await CoreConfigHandler.GenerateClientSpeedtestConfig(_config, context, testItem, configPath);
        if (result.Success != true)
        {
            return null;
        }

        var coreType = context.RunCoreType;
        var coreInfo = CoreInfoManager.Instance.GetCoreInfo(coreType);
        var process = await RunProcess(coreInfo, fileName, true, false);
        if (process is not null) process.TemporaryConfigPath = configPath;
        else if (File.Exists(configPath)) File.Delete(configPath);
        return process;
    }

    public async Task CoreStop(bool keepEntryHop = false)
    {
        await _lifecycleGate.WaitAsync();
        try { await CoreStopExclusive(keepEntryHop); }
        finally { _lifecycleGate.Release(); }
    }

    private async Task CoreStopExclusive(bool keepEntryHop = false)
    {
        _chainReady = false;
        _trafficVerified = false;
        ActiveProfileId = null;
        Interlocked.Increment(ref _intentionalStopDepth);
        try
        {
            if (!keepEntryHop) await EntryHopService.StopAsync();
            if (_linuxSudo)
            {
                await CoreAdminManager.Instance.KillProcessAsLinuxSudo();
                _linuxSudo = false;
            }

            if (_processService != null)
            {
                await _processService.StopAsync();
                _processService.Dispose();
                _processService = null;
            }

            if (_processPreService != null)
            {
                await _processPreService.StopAsync();
                _processPreService.Dispose();
                _processPreService = null;
            }
            if (_foxProcess is not null) { await _foxProcess.StopAsync(); _foxProcess.Dispose(); _foxProcess = null; }
            _activeConfigHash = null; _chainReady = false;
        }
        catch (Exception ex)
        {
            Logging.SaveLog(_tag, ex);
        }
        finally
        {
            Interlocked.Decrement(ref _intentionalStopDepth);
        }
    }

    #region Private

    private async Task CoreStart(CoreConfigContext context)
    {
        var node = context.Node;
        var coreType = AppManager.Instance.GetCoreType(node, node.ConfigType);
        var coreInfo = CoreInfoManager.Instance.GetCoreInfo(coreType);

        var displayLog = node.ConfigType != EConfigType.Custom || node.DisplayLog;
        var proc = await RunProcess(coreInfo, Global.CoreConfigFileName, displayLog, true, context.IsTunEnabled);
        if (proc is null) throw new IOException(LastStartupError ?? "Could not start the connection core");
        _processService = proc;
        proc.Exited += exitCode =>
        {
            if (ReferenceEquals(_processService, proc)
                && !proc.StopRequested
                && Volatile.Read(ref _intentionalStopDepth) == 0)
            {
                Logging.SaveLog($"CoreHandler: active core exited unexpectedly with code {exitCode}.");
                var handler = UnexpectedExit;
                if (handler != null)
                {
                    _ = handler(exitCode);
                }
            }
        };
    }

    private async Task CoreStartPreService(CoreConfigContext? preContext)
    {
        if (_processService is { HasExited: false } && preContext != null)
        {
            var preCoreType = preContext?.Node?.CoreType ?? ECoreType.sing_box;
            var fileName = Utils.GetBinConfigPath(Global.CorePreConfigFileName);
            // Already generated and hashed with the main config under the lifecycle gate.
            if (File.Exists(fileName))
            {
                var coreInfo = CoreInfoManager.Instance.GetCoreInfo(preCoreType);
                var proc = await RunProcess(coreInfo, Global.CorePreConfigFileName, true, true, preContext.IsTunEnabled);
                if (proc is null)
                {
                    await CoreStopExclusive();
                    throw new IOException(LastStartupError ?? "Could not start the proxy/TUN bridge");
                }
                _processPreService = proc;
                proc.Exited += code => {
                    if (ReferenceEquals(_processPreService, proc) && !proc.StopRequested && Volatile.Read(ref _intentionalStopDepth) == 0)
                        _ = StopAfterBridgeFailureAsync(code, proc);
                };
            }
        }
    }

    private async Task StopAfterBridgeFailureAsync(int code, ProcessService failedProcess)
    {
        try {
            await _lifecycleGate.WaitAsync();
            try {
            // An exit notification can wait behind a replacement. It must not stop
            // the new session or resurrect an intentionally stopped one.
            if (failedProcess.StopRequested || (!ReferenceEquals(_foxProcess, failedProcess)
                && !ReferenceEquals(_processPreService, failedProcess))) return;
            Logging.SaveLog($"CoreHandler: proxy/TUN bridge exited with code {code}; stopping the full chain.");
            await CoreStopExclusive();
            } finally { _lifecycleGate.Release(); }
            if (UnexpectedExit is { } handler) await handler(code);
        } catch (Exception error) { Logging.SaveLog("Bridge failure cleanup", error); }
    }

    private async Task UpdateFunc(bool notify, string msg)
    {
        await (_updateFunc?.Invoke(notify, msg) ?? Task.CompletedTask);
    }

    private static async Task WaitForProxyPort(CoreConfigContext? preContext)
    {
        if (preContext is null)
        {
            return;
        }
        if (!preContext.IsTunEnabled)
        {
            return;
        }

        using var rootCts = new CancellationTokenSource(Global.LocalFetch);
        var rootToken = rootCts.Token;

        var port = preContext.Node.Port;
        // SOCKS5 client greeting: VER=5, NMETHODS=1, METHOD=0x00 (no auth)
        ReadOnlyMemory<byte> greeting = new byte[] { 0x05, 0x01, 0x00 };
        var buf = new byte[2];

        while (!rootToken.IsCancellationRequested)
        {
            using var tcp = new TcpClient();
            using var attemptCts = new CancellationTokenSource(TimeSpan.FromMilliseconds(50));
            using var linkedCts = CancellationTokenSource.CreateLinkedTokenSource(rootToken, attemptCts.Token);
            var linkedToken = linkedCts.Token;
            try
            {
                await tcp.ConnectAsync(Global.Loopback, port, linkedToken);
                var stream = tcp.GetStream();

                await stream.WriteAsync(greeting, linkedToken);

                await stream.ReadExactlyAsync(buf.AsMemory(0, 2), linkedToken);

                // Server selection: VER=5, METHOD=0x00 — proxy is fully ready
                if (buf[0] == 0x05 && buf[1] == 0x00)
                {
                    return;
                }
            }
            catch (OperationCanceledException)
            {
                if (!rootToken.IsCancellationRequested)
                {
                    continue;
                }
                throw new TimeoutException($"SOCKS endpoint {port} did not become ready; the TUN bridge was not started.");
            }
            catch (SocketException ex) when (ex.SocketErrorCode == SocketError.ConnectionRefused)
            {
                // Connection refused, proxy not ready yet, wait 50ms before retrying
                try
                {
                    await Task.Delay(50, rootToken);
                }
                catch (OperationCanceledException)
                {
                    throw new TimeoutException($"SOCKS endpoint {port} did not become ready; the TUN bridge was not started.");
                }
            }
            catch
            {
                // Ignore other exceptions and continue
            }
        }
        throw new TimeoutException($"SOCKS endpoint {port} did not become ready; the TUN bridge was not started.");
    }

    #endregion Private

    #region Process

    /// <summary>
    ///     Decides whether a core launch must be elevated on non-Windows platforms.
    ///     The TUN state comes from the immutable <see cref="CoreConfigContext" /> snapshot that
    ///     generated the config, never from the live mutable config: the generated config and the
    ///     launch mode must always agree, even if TUN is toggled while a reload is in flight.
    /// </summary>
    public static bool ShouldRunAsSudo(bool isTunLaunch, ECoreType? coreType, bool isNonWindows)
    {
        return isTunLaunch
            && coreType is ECoreType.sing_box or ECoreType.mihomo or ECoreType.Xray
            && isNonWindows;
    }

    private async Task<ProcessService?> RunProcess(CoreInfo? coreInfo, string configPath, bool displayLog, bool mayNeedSudo, bool isTunLaunch = false)
    {
        string fileName; string msg;
        try { fileName = CoreInfoManager.Instance.GetCoreExecFile(coreInfo, out msg); }
        catch (Exception error) { LastStartupError = error.Message; await UpdateFunc(false, error.Message); return null; }
        if (fileName.IsNullOrEmpty())
        {
            LastStartupError = msg;
            await UpdateFunc(false, msg);
            return null;
        }

        try
        {
            NativeLaunchPolicy.Validate(fileName);
            if (coreInfo?.CoreType == ECoreType.sing_box) {
                var path = Utils.GetBinConfigPath(configPath);
                if (JsonNode.Parse(await File.ReadAllTextAsync(path)) is JsonObject root) {
                    var log = root["log"] as JsonObject ?? new JsonObject();
                    log["level"] = "info"; log["disabled"] = false; log.Remove("output"); root["log"] = log;
                    await File.WriteAllTextAsync(path, root.ToJsonString());
                }
                if (Utils.IsWindows() && isTunLaunch) {
                    WindowsTunRuntime.StageDriver(fileName, Utils.GetBinConfigPath());
                    WindowsTunRuntime.PrepareRetry(path);
                }
            }
            if (mayNeedSudo
                && ShouldRunAsSudo(isTunLaunch, coreInfo.CoreType, Utils.IsNonWindows())
                && !Utils.IsAdministrator())
            {
                _linuxSudo = true;
                await CoreAdminManager.Instance.Init(_config, _updateFunc);
                return await CoreAdminManager.Instance.RunProcessAsLinuxSudo(fileName, coreInfo, configPath);
            }

            try { return await RunProcessNormal(fileName, coreInfo, configPath, displayLog, isTunLaunch); }
            catch (Exception startup) when (Utils.IsWindows() && isTunLaunch && coreInfo.CoreType == ECoreType.sing_box
                && WindowsTunRuntime.IsMissingInterfaceFailure(startup.Message)) {
                if (!WindowsTunRuntime.PrepareRetry(Utils.GetBinConfigPath(configPath))) throw;
                Logging.SaveLog("TUN adapter was not registered; retrying once with a fresh DicodePing-owned interface.");
                return await RunProcessNormal(fileName, coreInfo, configPath, displayLog, isTunLaunch);
            }
        }
        catch (Exception ex)
        {
            LastStartupError = ex.Message;
            if (NativeLaunchPolicy.RecordLoaderFailure(fileName, ex)) {
                Logging.SaveLog("Core loader rejected the executable; automatic repeated launches disabled.");
                try { NativeLaunchPolicy.Validate(fileName); } catch (Exception failure) { await UpdateFunc(false, failure.Message); }
            } else await UpdateFunc(false, ex.Message);
            return null;
        }
    }

    private async Task<ProcessService?> RunProcessNormal(string fileName, CoreInfo? coreInfo, string configPath, bool displayLog, bool isTunLaunch = false)
    {
        var environmentVars = new Dictionary<string, string>();
        foreach (var kv in coreInfo.Environment)
        {
            environmentVars[kv.Key] = string.Format(kv.Value, coreInfo.AbsolutePath ? Utils.GetBinConfigPath(configPath).AppendQuotes() : configPath);
        }

        // Belt and braces: some cores resolve geo assets next to their own exe even
        // though XRAY_LOCATION_ASSET points at bin/. Copy the files down so a missing
        // asset can never be the reason a core dies on startup.
        try
        {
            var coreDir = Path.GetDirectoryName(fileName);
            if (!coreDir.IsNullOrEmpty())
            {
                foreach (var geo in new[] { "geoip.dat", "geosite.dat" })
                {
                    var source = Utils.GetBinPath(geo);
                    var target = Path.Combine(coreDir, geo);
                    if (File.Exists(source) && Path.GetFullPath(source) != Path.GetFullPath(target)
                        && (!File.Exists(target) || new FileInfo(source).Length != new FileInfo(target).Length
                            || File.GetLastWriteTimeUtc(source) > File.GetLastWriteTimeUtc(target)))
                    {
                        File.Copy(source, target, true);
                    }
                }
            }
        }
        catch (Exception ex)
        {
            Logging.SaveLog("Copy geo assets", ex);
        }

        var procService = new ProcessService(
            fileName: fileName,
            arguments: string.Format(coreInfo.Arguments, coreInfo.AbsolutePath ? Utils.GetBinConfigPath(configPath).AppendQuotes() : configPath),
            workingDirectory: Utils.GetBinConfigPath(),
            // Always capture output: the gui log must contain the core's own
            // diagnostics, otherwise "see the report" points at an empty page.
            displayLog: true,
            redirectInput: false,
            environmentVars: environmentVars,
            updateFunc: _updateFunc
        );

        try {
            await procService.StartAsync();
            AddProcessJob(procService.Handle);
            if (coreInfo.CoreType == ECoreType.sing_box) await procService.WaitForStartupAsync(TimeSpan.FromSeconds(30));
            else await Task.Delay(100);
            if (procService.HasExited) throw new IOException(ResUI.FailedToRunCore + Environment.NewLine + procService.RecentOutput);
        } catch { await procService.StopAsync(); procService.Dispose(); throw; }
        return procService;
    }

    private void AddProcessJob(nint processHandle)
    {
        if (Utils.IsWindows())
        {
            _processJob ??= new();
            try
            {
                _processJob?.AddProcess(processHandle);
            }
            catch { }
        }
    }

    #endregion Process
}
