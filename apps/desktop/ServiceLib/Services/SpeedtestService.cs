using ServiceLib.UdpTest;

namespace ServiceLib.Services;

public class SpeedtestService(Config config, Func<SpeedTestResult, Task> updateFunc)
{
    private static readonly string _tag = "SpeedtestService";
    private readonly Config? _config = config;
    private readonly Func<SpeedTestResult, Task>? _updateFunc = updateFunc;
    private readonly Lock _runLock = new();
    private readonly List<CancellationTokenSource> _runCtsList = [];
    private readonly int _speedTestPageSize = config.SpeedTestItem.SpeedTestPageSize ?? Global.SpeedTestPageSize;
    private readonly TimeSpan _delayInterval = TimeSpan.FromSeconds(config.SpeedTestItem.SpeedTestDelayInterval ?? 1);

    public Task RunLoop(ESpeedActionType actionType, List<ProfileItem> selecteds, CancellationToken ct = default)
    {
        CancellationTokenSource runCts;

        lock (_runLock)
        {
            runCts = CancellationTokenSource.CreateLinkedTokenSource(ct);

            _runCtsList.Add(runCts);
        }

        return RunLoopAsync(actionType, selecteds, runCts);
    }

    public void ExitLoop()
    {
        var counter = 0;
        List<CancellationTokenSource> listToCancel;

        lock (_runLock)
        {
            listToCancel = _runCtsList.ToList();
            counter = listToCancel.Count;
        }

        foreach (var cts in listToCancel)
        {
            try
            {
                cts.Cancel();
            }
            catch (ObjectDisposedException)
            {
                // Ignored
            }
        }

        if (counter > 0)
        {
            _ = UpdateFunc("", ResUI.SpeedtestingStop);
        }
    }

    private async Task RunLoopAsync(ESpeedActionType actionType, List<ProfileItem> selecteds, CancellationTokenSource runCts)
    {
        try
        {
            await RunAsync(actionType, selecteds, runCts.Token);
        }
        catch (OperationCanceledException) when (runCts.IsCancellationRequested)
        {
            // Ignored
        }
        finally
        {
            try
            {
                await ProfileExManager.Instance.SaveTo();
                await UpdateFunc("", ResUI.SpeedtestingCompleted);
            }
            finally
            {
                lock (_runLock) { _runCtsList.Remove(runCts); }
                runCts.Dispose();
            }
        }
    }

    private async Task RunAsync(ESpeedActionType actionType, List<ProfileItem> selecteds, CancellationToken ct = default)
    {
        var lstSelected = await GetClearItem(actionType, selecteds);
        var completedIds = new ConcurrentDictionary<string, byte>();

        try
        {
            switch (actionType)
            {
                case ESpeedActionType.Tcping:
                    await RunTcpingAsync(lstSelected, completedIds, ct);
                    break;

                case ESpeedActionType.Realping:
                    await RunRealPingBatchAsync(lstSelected, completedIds, 0, ct);
                    break;

                case ESpeedActionType.Location:
                    await RunLocationBatchAsync(lstSelected, completedIds, ct);
                    break;
                case ESpeedActionType.Sanctions:
                    await RunSanctionsBatchAsync(lstSelected, completedIds, ct);
                    break;

                case ESpeedActionType.UdpTest:
                    await RunUdpTestBatchAsync(lstSelected, completedIds, 0, ct);
                    break;

                case ESpeedActionType.Speedtest:
                    await RunMixedTestAsync(lstSelected, completedIds, Math.Clamp(_config.SpeedTestItem.MixedConcurrencyCount, 2, 4), true, ct, false);
                    break;

                case ESpeedActionType.Mixedtest:
                    await RunMixedTestAsync(lstSelected, completedIds, _config.SpeedTestItem.MixedConcurrencyCount, true,
                        ct);
                    break;
            }
        }
        catch (OperationCanceledException) when (ct.IsCancellationRequested)
        {
            _ = UpdateFunc("", ResUI.SpeedtestingStop);
            await SetTestResultAsync(lstSelected.Where(it => !completedIds.ContainsKey(it.IndexId)).ToList(),
                actionType, ResUI.SpeedtestingSkip).ConfigureAwait(false);
        }
        catch (Exception ex)
        {
            Logging.SaveLog(_tag, ex);
            _ = UpdateFunc("", ex.Message);
            await SetTestResultAsync(lstSelected.Where(it => !completedIds.ContainsKey(it.IndexId)).ToList(), actionType, ResUI.FailedToRunCore);
        }
    }

    private async Task<List<ServerTestItem>> GetClearItem(ESpeedActionType actionType, List<ProfileItem> selecteds)
    {
        var lstSelected = new List<ServerTestItem>(selecteds.Count);
        var ids = selecteds.Where(it => !it.IndexId.IsNullOrEmpty()
            && (it.ConfigType == EConfigType.Custom || it.ConfigType.IsComplexType() || it.Port > 0))
            .Select(it => it.IndexId)
            .ToList();
        var profileMap = await AppManager.Instance.GetProfileItemsByIndexIdsAsMap(ids);
        for (var i = 0; i < selecteds.Count; i++)
        {
            var it = selecteds[i];
            if (it.ConfigType == EConfigType.Custom && (actionType is ESpeedActionType.Tcping or ESpeedActionType.Location or ESpeedActionType.UdpTest || it.CoreType is not (ECoreType.Xray or ECoreType.sing_box))) continue;

            if (it.ConfigType != EConfigType.Custom && !it.ConfigType.IsComplexType() && it.Port <= 0)
            {
                continue;
            }

            var profile = profileMap.GetValueOrDefault(it.IndexId, it);
            lstSelected.Add(new ServerTestItem()
            {
                IndexId = it.IndexId,
                Address = it.Address,
                Port = it.Port,
                ConfigType = it.ConfigType,
                QueueNum = i,
                Profile = profile,
                CoreType = AppManager.Instance.GetCoreType(profile, it.ConfigType),
            });
        }

        //clear test result
        // Pending state is applied once by the caller; avoid thousands of redundant UI dispatches.

        if (lstSelected.Count > 1 && (actionType == ESpeedActionType.Speedtest || actionType == ESpeedActionType.Mixedtest))
        {
            NoticeManager.Instance.Enqueue(ResUI.SpeedtestingPressEscToExit);
        }

        return lstSelected;
    }

    private async Task SetTestResultAsync(List<ServerTestItem> lstSelected, ESpeedActionType actionType, string message)
    {
        foreach (var it in lstSelected)
        {
            switch (actionType)
            {
                case ESpeedActionType.Tcping:
                case ESpeedActionType.Realping:
                case ESpeedActionType.UdpTest:
                    await UpdateFunc(it.IndexId, message, "");
                    break;

                case ESpeedActionType.Speedtest:
                    await UpdateFunc(it.IndexId, "", message);
                    break;

                case ESpeedActionType.Location:
                    await UpdateIpInfoFunc(it.IndexId, message);
                    break;
                case ESpeedActionType.Sanctions:
                    await UpdateSanctionsFunc(it.IndexId, message);
                    break;
                case ESpeedActionType.Mixedtest:
                    await UpdateFunc(it.IndexId, message, message);
                    break;
            }
        }
    }

    private async Task RunLocationBatchAsync(List<ServerTestItem> selecteds,
        ConcurrentDictionary<string, byte> completedIds, CancellationToken ct)
    {
        foreach (var batch in GetTestBatchItem(selecteds, Math.Max(1, _speedTestPageSize)))
        {
            ct.ThrowIfCancellationRequested();
            ProcessService? process = null;
            try
            {
                process = await CoreManager.Instance.LoadCoreConfigSpeedtest(batch);
                if (process is null) { await SetTestResultAsync(batch, ESpeedActionType.Location, ResUI.FailedToRunCore); continue; }
                ct.ThrowIfCancellationRequested();
                await Parallel.ForEachAsync(batch, new ParallelOptions { MaxDegreeOfParallelism = 8, CancellationToken = ct }, async (item, token) =>
                {
                    if (!item.AllowTest) { await UpdateIpInfoFunc(item.IndexId, ResUI.SpeedtestingSkip); return; }
                    var ip = await ConnectionHandler.GetIPInfo(new WebProxy($"socks5://{Global.Loopback}:{item.Port}"), token);
                    var text = ip?.ToString() ?? "—";
                    ProfileExManager.Instance.SetTestIpInfo(item.IndexId, text);
                    await UpdateIpInfoFunc(item.IndexId, text);
                    completedIds.TryAdd(item.IndexId, 0);
                });
            }
            finally { if (process is not null) { await process.StopAsync(); process.Dispose(); } }
        }
    }

    private async Task RunSanctionsBatchAsync(List<ServerTestItem> selecteds,
        ConcurrentDictionary<string, byte> completedIds, CancellationToken ct)
    {
        foreach (var batch in GetTestBatchItem(selecteds, Math.Max(1, Math.Min(8, _speedTestPageSize))))
        {
            ct.ThrowIfCancellationRequested();
            ProcessService? process = null;
            try
            {
                process = await CoreManager.Instance.LoadCoreConfigSpeedtest(batch);
                if (process is null) { await SetTestResultAsync(batch, ESpeedActionType.Sanctions, ResUI.FailedToRunCore); continue; }
                ct.ThrowIfCancellationRequested();
                await Parallel.ForEachAsync(batch, new ParallelOptions { MaxDegreeOfParallelism = 8, CancellationToken = ct }, async (item, token) =>
                {
                    if (!item.AllowTest) { await UpdateSanctionsFunc(item.IndexId, ResUI.SpeedtestingSkip); return; }
                    await DoSanctionsTest(item, token);
                    completedIds.TryAdd(item.IndexId, 0);
                });
            }
            finally { if (process is not null) { await process.StopAsync(); process.Dispose(); } }
        }
    }

    private async Task DoSanctionsTest(ServerTestItem item, CancellationToken ct)
    {
        var proxy = new WebProxy($"socks5://{Global.Loopback}:{item.Port}");
        var result = await ConnectionHandler.TestSanctionsAccessAsync(proxy, ct);
        var text = result.Accessible
            ? string.Format(ResUI.DicodeSanctionsAccessible, result.Passed, result.Total)
            : string.Format(ResUI.DicodeSanctionsRestricted, result.Passed, result.Total);
        // Show which services failed so the verdict is transparent and verifiable.
        var failedNames = string.Join(", ", result.Details.Where(d => !d.Ok).Select(d => d.Name).Take(6));
        if (failedNames.IsNotEmpty())
        {
            text += $" · {failedNames}";
        }
        ProfileExManager.Instance.SetSanctionsInfo(item.IndexId, text);
        await UpdateSanctionsFunc(item.IndexId, text);
    }

    private async Task RunTcpingAsync(List<ServerTestItem> selecteds,
        ConcurrentDictionary<string, byte> completedIds, CancellationToken ct = default)
    {
        var pageSize = Math.Min(selecteds.Count, _speedTestPageSize);
        var lstBatch = GetTestBatchItem(selecteds, pageSize);

        foreach (var lst in lstBatch)
        {
            ct.ThrowIfCancellationRequested();

            var parallelOptions = new ParallelOptions
            {
                MaxDegreeOfParallelism = lst.Count,
                CancellationToken = ct,
            };

            await Parallel.ForEachAsync(lst, parallelOptions, async (item, innerCt) =>
            {
                try
                {
                    var responseTime = await GetTcpingTime(item.Address, item.Port, innerCt);

                    ProfileExManager.Instance.SetTestDelay(item.IndexId, responseTime);
                    await UpdateFunc(item.IndexId, responseTime.ToString());
                    completedIds.TryAdd(item.IndexId, 0);
                }
                catch (OperationCanceledException) when (ct.IsCancellationRequested)
                {
                    throw;
                }
                catch (Exception ex)
                {
                    Logging.SaveLog(_tag, ex);
                }
            });

            await Task.Delay(_delayInterval, ct);
        }
    }

    private async Task RunRealPingBatchAsync(List<ServerTestItem> lstSelected,
        ConcurrentDictionary<string, byte> completedIds, int pageSize = 0, CancellationToken ct = default)
    {
        if (pageSize <= 0)
        {
            pageSize = Math.Min(lstSelected.Count, _speedTestPageSize);
        }
        var lstTest = GetTestBatchItem(lstSelected, pageSize);

        List<ServerTestItem> lstFailed = [];
        foreach (var lst in lstTest)
        {
            var ret = await RunRealPingAsync(lst, completedIds, ct);
            if (ret == false)
            {
                lstFailed.AddRange(lst);
            }
            await Task.Delay(_delayInterval, ct);
        }

        //Retest the failed part
        var pageSizeNext = pageSize / 2;
        if (lstFailed.Count > 0 && pageSizeNext > 0)
        {
            ct.ThrowIfCancellationRequested();

            await UpdateFunc("", string.Format(ResUI.SpeedtestingTestFailedPart, lstFailed.Count));

            if (pageSizeNext > _config.SpeedTestItem.MixedConcurrencyCount)
            {
                await RunRealPingBatchAsync(lstFailed, completedIds, pageSizeNext, ct);
            }
            else
            {
                await RunMixedTestAsync(lstFailed, completedIds, _config.SpeedTestItem.MixedConcurrencyCount, false, ct);
            }
        }
        else if (lstFailed.Count > 0)
        {
            await SetTestResultAsync(lstFailed, ESpeedActionType.Realping, ResUI.FailedToRunCore);
        }
    }

    private async Task<bool> RunRealPingAsync(List<ServerTestItem> selecteds,
        ConcurrentDictionary<string, byte> completedIds, CancellationToken ct = default)
    {
        ProcessService processService = null;
        try
        {
            processService = await CoreManager.Instance.LoadCoreConfigSpeedtest(selecteds);
            if (processService is null)
            {
                return false;
            }
            ct.ThrowIfCancellationRequested();

            var parallelOptions = new ParallelOptions
            {
                MaxDegreeOfParallelism = selecteds.Count,
                CancellationToken = ct,
            };

            await Parallel.ForEachAsync(selecteds, parallelOptions, async (it, innerCt) =>
            {
                if (!it.AllowTest)
                {
                    await UpdateFunc(it.IndexId, ResUI.SpeedtestingSkip);
                    completedIds.TryAdd(it.IndexId, 0);
                    return;
                }

                try
                {
                    await DoRealPing(it, completedIds, innerCt);
                }
                catch (OperationCanceledException) when (ct.IsCancellationRequested)
                {
                    throw;
                }
                catch (Exception ex)
                {
                    Logging.SaveLog(_tag, ex);
                }
            });
        }
        catch (OperationCanceledException) when (ct.IsCancellationRequested)
        {
            throw;
        }
        catch (Exception ex)
        {
            Logging.SaveLog(_tag, ex);
        }
        finally
        {
            if (processService != null)
            {
                await processService.StopAsync();
                processService.Dispose();
            }
        }
        return true;
    }

    private async Task RunUdpTestBatchAsync(List<ServerTestItem> lstSelected,
        ConcurrentDictionary<string, byte> completedIds, int pageSize = 0, CancellationToken ct = default)
    {
        if (pageSize <= 0)
        {
            pageSize = Math.Min(lstSelected.Count, _speedTestPageSize);
        }
        var lstTest = GetTestBatchItem(lstSelected, pageSize);

        List<ServerTestItem> lstFailed = [];
        foreach (var lst in lstTest)
        {
            var ret = await RunUdpTestAsync(lst, completedIds, ct);
            if (ret == false)
            {
                lstFailed.AddRange(lst);
            }
            await Task.Delay(_delayInterval, ct);
        }

        //Retest the failed part
        if (lstFailed.Count > 0)
        {
            ct.ThrowIfCancellationRequested();

            await UpdateFunc("", string.Format(ResUI.SpeedtestingTestFailedPart, lstFailed.Count));

            await RunUdpTestAsync(lstFailed, completedIds, ct);
        }
    }

    private async Task<bool> RunUdpTestAsync(List<ServerTestItem> selecteds,
        ConcurrentDictionary<string, byte> completedIds, CancellationToken ct = default)
    {
        ProcessService processService = null;
        try
        {
            processService = await CoreManager.Instance.LoadCoreConfigSpeedtest(selecteds);
            if (processService is null)
            {
                return false;
            }
            ct.ThrowIfCancellationRequested();

            var parallelOptions = new ParallelOptions
            {
                MaxDegreeOfParallelism = selecteds.Count,
                CancellationToken = ct,
            };

            await Parallel.ForEachAsync(selecteds, parallelOptions, async (it, innerCt) =>
            {
                if (!it.AllowTest)
                {
                    await UpdateFunc(it.IndexId, ResUI.SpeedtestingSkip);
                    completedIds.TryAdd(it.IndexId, 0);
                    return;
                }

                try
                {
                    await DoUdpTest(it, completedIds, innerCt);
                }
                catch (OperationCanceledException) when (ct.IsCancellationRequested)
                {
                    throw;
                }
                catch (Exception ex)
                {
                    Logging.SaveLog(_tag, ex);
                }
            });
        }
        catch (OperationCanceledException) when (ct.IsCancellationRequested)
        {
            throw;
        }
        catch (Exception ex)
        {
            Logging.SaveLog(_tag, ex);
        }
        finally
        {
            if (processService != null)
            {
                await processService.StopAsync();
                processService.Dispose();
            }
        }
        return true;
    }

    private async Task RunMixedTestAsync(List<ServerTestItem> selecteds,
        ConcurrentDictionary<string, byte> completedIds, int concurrencyCount, bool blSpeedTest,
        CancellationToken ct = default, bool updateDelay = true)
    {
        // Each transfer owns its downloader and cannot cancel another server.


        var parallelOptions = new ParallelOptions
        {
            MaxDegreeOfParallelism = concurrencyCount,
            CancellationToken = ct,
        };

        await Parallel.ForEachAsync(selecteds, parallelOptions, async (it, innerCt) =>
        {
            innerCt.ThrowIfCancellationRequested();

            ProcessService processService = null;
            try
            {
                processService = await CoreManager.Instance.LoadCoreConfigSpeedtest(it);
                if (processService is null)
                {
                    await UpdateFunc(it.IndexId, "", ResUI.FailedToRunCore);
                    return;
                }

                innerCt.ThrowIfCancellationRequested();

                var delay = await DoRealPing(it, completedIds, innerCt, updateDelay);
                if (blSpeedTest)
                {
                    if (delay > 0)
                    {
                        await DoSpeedTest(it, completedIds, innerCt);
                    }
                    else
                    {
                        await UpdateFunc(it.IndexId, "", ResUI.SpeedtestingSkip);
                    }
                }
            }
            catch (OperationCanceledException) when (ct.IsCancellationRequested)
            {
                throw;
            }
            catch (Exception ex)
            {
                Logging.SaveLog(_tag, ex);
            }
            finally
            {
                if (processService != null)
                {
                    await processService.StopAsync();
                    processService.Dispose();
                }
            }
        });
    }

    private async Task<int> DoRealPing(ServerTestItem it,
        ConcurrentDictionary<string, byte> completedIds, CancellationToken ct = default, bool updateDelay = true)
    {
        var webProxy = new WebProxy($"socks5://{Global.Loopback}:{it.Port}");
        var responseTime = await ConnectionHandler.GetRealPingTime(webProxy, ct);

        if (updateDelay)
        {
            ProfileExManager.Instance.SetTestDelay(it.IndexId, responseTime);
            await UpdateFunc(it.IndexId, responseTime.ToString());
        }

        completedIds.TryAdd(it.IndexId, 0);
        return responseTime;
    }

    private async Task DoSpeedTest(ServerTestItem item,
        ConcurrentDictionary<string, byte> completedIds, CancellationToken ct = default)
    {
        var proxy = new WebProxy($"socks5://{Global.Loopback}:{item.Port}");
        using var handler = new HttpClientHandler { Proxy = proxy, UseProxy = true };
        using var client = new HttpClient(handler) { Timeout = Timeout.InfiniteTimeSpan };
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(ct);
        timeout.CancelAfter(TimeSpan.FromSeconds(Math.Clamp(_config.SpeedTestItem.SpeedTestTimeout, 3, 20)));
        long bytes = 0;
        var timer = new Stopwatch();
        try
        {
            using var response = await client.GetAsync(_config.SpeedTestItem.SpeedTestUrl, HttpCompletionOption.ResponseHeadersRead, timeout.Token);
            response.EnsureSuccessStatusCode();
            await using var stream = await response.Content.ReadAsStreamAsync(timeout.Token);
            var buffer = new byte[64 * 1024];
            timer.Start();
            while (true)
            {
                var count = await stream.ReadAsync(buffer, timeout.Token);
                if (count == 0) break;
                bytes += count;
            }
        }
        catch (OperationCanceledException) when (!ct.IsCancellationRequested) { /* A timed sample is complete. */ }
        catch (OperationCanceledException) { throw; }
        catch (Exception ex) { Logging.SaveLog(_tag, ex); }
        finally { timer.Stop(); }
        ct.ThrowIfCancellationRequested();
        var speed = timer.Elapsed.TotalSeconds > 0 ? Math.Round((decimal)(bytes / timer.Elapsed.TotalSeconds / 1_000_000), 2) : 0;
        ProfileExManager.Instance.SetTestSpeed(item.IndexId, speed);
        await UpdateFunc(item.IndexId, "", speed > 0 ? speed.ToString("0.00") : ResUI.SpeedtestingSkip);
        completedIds.TryAdd(item.IndexId, 0);
    }

    private async Task<int> DoUdpTest(ServerTestItem it,
        ConcurrentDictionary<string, byte> completedIds, CancellationToken ct = default)
    {
        var udpService = UdpTestService.CreateFromTarget(_config?.SpeedTestItem.UdpTestTarget, out var udpTestUrl);
        var responseTime = (int)(await udpService.SendUdpRequestAsync(udpTestUrl, it.Port, ct)).TotalMilliseconds;

        if (responseTime > 0) ProfileExManager.Instance.SetTestDelay(it.IndexId, responseTime);
        await UpdateFunc(it.IndexId, responseTime.ToString());
        completedIds.TryAdd(it.IndexId, 0);
        return responseTime;
    }

    private async Task<int> GetTcpingTime(string? host, int port, CancellationToken ct = default)
    {
        if (host.IsNullOrEmpty() || port <= 0) return -1;
        using var client = new TcpClient();
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(ct);
        timeout.CancelAfter(TimeSpan.FromSeconds(3));
        var timer = Stopwatch.StartNew();
        try
        {
            // Connect by host so both IPv4 and IPv6 addresses can be tried.
            await client.ConnectAsync(host, port, timeout.Token);
            return Math.Max(1, (int)timer.ElapsedMilliseconds);
        }
        catch (OperationCanceledException) when (ct.IsCancellationRequested) { throw; }
        catch { return -1; }
    }

    private List<List<ServerTestItem>> GetTestBatchItem(List<ServerTestItem> lstSelected, int pageSize)
    {
        List<List<ServerTestItem>> lstTest = [];
        var lst1 = lstSelected.Where(t => t.CoreType == ECoreType.Xray).ToList();
        var lst2 = lstSelected.Where(t => t.CoreType == ECoreType.sing_box).ToList();

        for (var num = 0; num < (int)Math.Ceiling(lst1.Count * 1.0 / pageSize); num++)
        {
            lstTest.Add(lst1.Skip(num * pageSize).Take(pageSize).ToList());
        }
        for (var num = 0; num < (int)Math.Ceiling(lst2.Count * 1.0 / pageSize); num++)
        {
            lstTest.Add(lst2.Skip(num * pageSize).Take(pageSize).ToList());
        }

        return lstTest;
    }

    private async Task UpdateFunc(string indexId, string delay, string speed = "")
    {
        await _updateFunc?.Invoke(new() { IndexId = indexId, Delay = delay, Speed = speed });
        if (indexId.IsNotEmpty() && speed.IsNotEmpty())
        {
            if (speed != ResUI.Speedtesting && speed != ResUI.SpeedtestingSkip && !decimal.TryParse(speed, out _)) ProfileExManager.Instance.SetTestSpeed(indexId, 0);
            ProfileExManager.Instance.SetTestMessage(indexId, speed);
        }
    }

    private async Task UpdateSanctionsFunc(string indexId, string value)
    {
        await _updateFunc?.Invoke(new() { IndexId = indexId, SanctionsInfo = value });
    }
    private async Task UpdateIpInfoFunc(string indexId, string ip)
    {
        await _updateFunc?.Invoke(new() { IndexId = indexId, IpInfo = ip });
    }
}
