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
    private readonly SemaphoreSlim _probeLaunchLock = new(1, 1);
    private const string _tag = "CoreHandler";

    public string? LastStartupError { get; private set; }
    private bool _chainReady;
    public bool IsRunning => _chainReady && _processService is { HasExited: false }
        && (_processPreService is null || !_processPreService.HasExited)
        && (_foxProcess is null || !_foxProcess.HasExited);
    public event Func<int, Task>? UnexpectedExit;

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

        var fox = FoxProfiles.Read(mainContext.Node);
        var generatedConfigHash = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(
            await File.ReadAllTextAsync(fileName) + (fox is null ? "" : $"|fox:{fox.AccountId}:{fox.Country}"))));
        if (IsRunning && string.Equals(_activeConfigHash, generatedConfigHash, StringComparison.Ordinal))
        {
            Logging.SaveLog("CoreHandler: identical generated configuration; keeping the active TUN process.");
            return;
        }

        await UpdateFunc(false, $"{node.GetSummary()}");
        await UpdateFunc(false, $"{Utils.GetRuntimeInfo()}");
        await UpdateFunc(false, string.Format(ResUI.StartService, DateTime.Now.ToString("yyyy/MM/dd HH:mm:ss")));
        await CoreStop(keepEntryHop: true);
        try {
        await EntryHopService.EnsureReadyAsync(mainContext);
        await Task.Delay(250);

        if (fox is not null) {
            using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(100));
            var helper = await FoxAccounts.StartProxyAsync(fox.AccountId, fox.Country, fox.HelperPort, timeout.Token);
            _foxProcess = helper;
            helper.Exited += code => { if (ReferenceEquals(_foxProcess, helper) && !helper.StopRequested && Volatile.Read(ref _intentionalStopDepth) == 0) _ = StopAfterBridgeFailureAsync(code); };
        }
        await CoreStart(mainContext);
        if (_processService is null) { await CoreStop(); return; }
        if (_foxProcess is { HasExited: true }) { await CoreStop(); throw new FoxException("helper", "Firefox proxy stopped during startup"); }
        await WaitForProxyPort(preContext);
        await CoreStartPreService(preContext);

        AppManager.Instance.RunningCoreType = preContext?.RunCoreType ?? mainContext.RunCoreType;

        if (_processService != null)
        {
            _activeConfigHash = generatedConfigHash; _chainReady = true;
            await UpdateFunc(true, $"{node.GetSummary()}");
        }
        } catch { await CoreStop(); throw; }
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

    private async Task<ProcessService?> StartProbeBatch(List<ServerTestItem> selecteds)
    {
        if (selecteds.Any(x => x.ConfigType == EConfigType.Custom || _config.EntryHopItem.Applies(x.Profile))) return null;
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
        if (!keepEntryHop) await EntryHopService.StopAsync();
        Interlocked.Increment(ref _intentionalStopDepth);
        try
        {
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
            var result = await CoreConfigHandler.GenerateClientConfig(preContext, fileName);
            if (result.Success)
            {
                var coreInfo = CoreInfoManager.Instance.GetCoreInfo(preCoreType);
                var proc = await RunProcess(coreInfo, Global.CorePreConfigFileName, true, true, preContext.IsTunEnabled);
                if (proc is null)
                {
                    await CoreStop();
                    throw new IOException(LastStartupError ?? "Could not start the proxy/TUN bridge");
                }
                _processPreService = proc;
                proc.Exited += code => {
                    if (ReferenceEquals(_processPreService, proc) && !proc.StopRequested && Volatile.Read(ref _intentionalStopDepth) == 0)
                        _ = StopAfterBridgeFailureAsync(code);
                };
            }
        }
    }

    private async Task StopAfterBridgeFailureAsync(int code)
    {
        try {
            Logging.SaveLog($"CoreHandler: proxy/TUN bridge exited with code {code}; stopping the full chain.");
            await CoreStop();
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

                var read = await stream.ReadAsync(buf.AsMemory(0, 2), linkedToken);

                // Server selection: VER=5, METHOD=0x00 — proxy is fully ready
                if (read == 2 && buf[0] == 0x05)
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
                Logging.SaveLog($"WaitForProxyPort Timeout waiting for proxy port {port} to be ready.");
                return;
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
                    Logging.SaveLog($"WaitForProxyPort Timeout waiting for proxy port {port} to be ready.");
                    return;
                }
            }
            catch
            {
                // Ignore other exceptions and continue
            }
        }
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
        catch (Exception error) { await UpdateFunc(mayNeedSudo, error.Message); return null; }
        if (fileName.IsNullOrEmpty())
        {
            await UpdateFunc(false, msg);
            return null;
        }

        try
        {
            NativeLaunchPolicy.Validate(fileName);
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
                try { NativeLaunchPolicy.Validate(fileName); } catch (Exception failure) { await UpdateFunc(mayNeedSudo, failure.Message); }
            } else await UpdateFunc(mayNeedSudo, ex.Message);
            return null;
        }
    }

    private async Task<ProcessService?> RunProcessNormal(string fileName, CoreInfo? coreInfo, string configPath, bool displayLog, bool isTunLaunch = false)
    {
        if (coreInfo?.CoreType == ECoreType.sing_box) {
            var path = Utils.GetBinConfigPath(configPath);
            if (JsonNode.Parse(await File.ReadAllTextAsync(path)) is JsonObject root) {
                var log = root["log"] as JsonObject ?? new JsonObject();
                log["level"] = "info"; log["disabled"] = false; log.Remove("output"); root["log"] = log;
                await File.WriteAllTextAsync(path, root.ToJsonString());
            }
            if (Utils.IsWindows() && isTunLaunch) WindowsTunRuntime.StageDriver(fileName, Utils.GetBinConfigPath());
        }
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
