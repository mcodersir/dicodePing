namespace ServiceLib.Services.Statistics;

public class StatisticsXrayService
{
    private long _sessionId = -1;
    private const long linkBase = 1024;
    private ServerSpeedItem _serverSpeedItem = new();
    private readonly Config _config;
    private readonly HttpClient _metricsClient = new(new SocketsHttpHandler { UseProxy = false }) { Timeout = TimeSpan.FromSeconds(3) };
    private readonly CancellationTokenSource _cts = new();
    private readonly Func<ServerSpeedItem, Task>? _updateFunc;
    private string Url => $"{Global.HttpProtocol}{Global.Loopback}:{AppManager.Instance.StatePort}/debug/vars";
    private static readonly string _tag = "StatisticsXrayService";

    public StatisticsXrayService(Config config, Func<ServerSpeedItem, Task> updateFunc)
    {
        _config = config;
        _updateFunc = updateFunc;

        Task.Run(Run);
    }

    public void Close()
    {
        try
        {
            _cts.Cancel();
        }
        catch (Exception ex)
        {
            Logging.SaveLog(_tag, ex);
        }
    }

    private async Task Run()
    {
        var token = _cts.Token;

        using var timer = new PeriodicTimer(TimeSpan.FromSeconds(1));
        while (!token.IsCancellationRequested)
        {
            try
            {
                if (!await timer.WaitForNextTickAsync(token).ConfigureAwait(false)) break;
                if (AppManager.Instance.RunningCoreType != ECoreType.Xray)
                {
                    continue;
                }

                var runtime = CoreManager.Instance;
                if (!runtime.IsRunning || runtime.ActiveProfileId is not { } profileId) continue;
                var session = runtime.SessionId;
                if (_sessionId != session) { _serverSpeedItem = new(); _sessionId = session; }
                var result = await _metricsClient.GetStringAsync($"http://{Global.Loopback}:{runtime.StatisticsPort}/debug/vars", token);
                if (!runtime.IsRunning || runtime.SessionId != session) continue;
                if (result != null)
                {
                    var server = ParseOutput(result) ?? new ServerSpeedItem();
                    server.IndexId = profileId;
                    await _updateFunc!.Invoke(server);
                }
            }
            catch (OperationCanceledException) when (token.IsCancellationRequested)
            {
                break;
            }
            catch
            {
                try { await Task.Delay(3000, token).ConfigureAwait(false); }
                catch (OperationCanceledException) when (token.IsCancellationRequested) { break; }
            }
        }
    }

    private ServerSpeedItem? ParseOutput(string result)
    {
        try
        {
            var source = JsonUtils.Deserialize<V2rayMetricsVars>(result);
            if (source?.stats?.outbound == null)
            {
                return null;
            }

            ServerSpeedItem server = new();
            foreach (var key in source.stats.outbound.Keys.Cast<string>())
            {
                var value = source.stats.outbound[key];
                if (value == null)
                {
                    continue;
                }
                var state = JsonUtils.Deserialize<V2rayMetricsVarsLink>(value.ToString());

                if (state is null) continue;
                if (key.StartsWith(Global.ProxyTag))
                {
                    server.ProxyUp += state.uplink / linkBase;
                    server.ProxyDown += state.downlink / linkBase;
                }
                else if (key == Global.DirectTag)
                {
                    server.DirectUp = state.uplink / linkBase;
                    server.DirectDown = state.downlink / linkBase;
                }
            }

            if (server.DirectDown < _serverSpeedItem.DirectDown || server.ProxyDown < _serverSpeedItem.ProxyDown
                || server.DirectUp < _serverSpeedItem.DirectUp || server.ProxyUp < _serverSpeedItem.ProxyUp)
            {
                _serverSpeedItem = new();
            }

            ServerSpeedItem curItem = new()
            {
                ProxyUp = server.ProxyUp - _serverSpeedItem.ProxyUp,
                ProxyDown = server.ProxyDown - _serverSpeedItem.ProxyDown,
                DirectUp = server.DirectUp - _serverSpeedItem.DirectUp,
                DirectDown = server.DirectDown - _serverSpeedItem.DirectDown,
            };
            _serverSpeedItem = server;
            return curItem;
        }
        catch
        {
            // ignored
        }

        return null;
    }
}
