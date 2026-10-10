namespace ServiceLib.Services;

/// <summary>Only persists a candidate after two successful requests through its complete proxy chain.</summary>
public static class FinalMaskDiscovery
{
    public static async Task<long> DiscoverAsync(Config config, ProfileItem original, Func<string, Task> progress, CancellationToken token)
    {
        if (original.StreamSecurity != "tls" || AppManager.Instance.GetCoreType(original, original.ConfigType) != ECoreType.Xray || original.ConfigType.IsComplexType())
            throw new NotSupportedException("FinalMask discovery requires an individual TLS profile using Xray");
        var identity = ConfigHandler.ConnectionIdentity(original);
        var masks = new[] { original.Finalmask ?? "", SniBlockPreset.Fragment,
            SniBlockPreset.Fragment.Replace("[\"6\",\"98\",\"1\"]", "[\"10-30\"]").Replace("[\"0\"]", "[\"1-3\"]") }.Distinct().ToList();
        using var overall = CancellationTokenSource.CreateLinkedTokenSource(token);
        overall.CancelAfter(TimeSpan.FromSeconds(90));
        var successes = new List<(string Mask, long Delay)>();
        for (var i = 0; i < masks.Count; i++)
        {
            overall.Token.ThrowIfCancellationRequested();
            await progress($"{i + 1} / {masks.Count}");
            var clone = JsonUtils.Deserialize<ProfileItem>(JsonUtils.Serialize(original))!;
            clone.Finalmask = masks[i];
            var item = new ServerTestItem { IndexId = clone.IndexId, Profile = clone, ConfigType = clone.ConfigType, CoreType = ECoreType.Xray, AllowTest = true };
            ProcessService? process = null;
            try
            {
                using var candidate = CancellationTokenSource.CreateLinkedTokenSource(overall.Token);
                candidate.CancelAfter(TimeSpan.FromSeconds(25));
                process = await CoreManager.Instance.LoadCoreConfigSpeedtest(item);
                candidate.Token.ThrowIfCancellationRequested();
                if (process is null) throw new IOException("Cannot start candidate core");
                var first = await EntryHopService.ProbeAsync(item.Port, config.SpeedTestItem.SpeedPingTestUrl, candidate.Token);
                var second = await EntryHopService.ProbeAsync(item.Port, config.SpeedTestItem.SpeedPingTestUrl, candidate.Token);
                successes.Add((masks[i], (first + second) / 2));
            }
            catch (OperationCanceledException) when (overall.IsCancellationRequested) { throw; }
            catch (Exception ex) { Logging.SaveLog("FinalMask candidate failed", ex); }
            finally { if (process is not null) { await process.StopAsync(); process.Dispose(); } }
        }
        if (successes.Count == 0) throw new IOException(ResUI.DicodeDiscoverFailed);
        var winner = successes.OrderBy(x => x.Delay).First();
        await ProfileOperationCoordinator.Gate.WaitAsync(overall.Token);
        try
        {
            var current = await AppManager.Instance.GetProfileItem(original.IndexId);
            if (current is null || ConfigHandler.ConnectionIdentity(current) != identity) throw new InvalidOperationException("Profile changed while discovery was running");
            current.Finalmask = winner.Mask;
            await ConfigHandler.AddServerCommon(config, current);
            ProfileExManager.Instance.SetTestDelay(current.IndexId, (int)winner.Delay);
            await ProfileExManager.Instance.SaveTo();
        }
        finally { ProfileOperationCoordinator.Gate.Release(); }
        return winner.Delay;
    }
}
