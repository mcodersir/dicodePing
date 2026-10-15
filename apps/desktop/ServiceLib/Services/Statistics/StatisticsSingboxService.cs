using System.Net.WebSockets;

namespace ServiceLib.Services.Statistics;

public class StatisticsSingboxService
{
    private readonly Config _config;
    private readonly TrafficKiBAccumulator _traffic = new();
    private readonly CancellationTokenSource _cts = new();
    private readonly Func<ServerSpeedItem, Task>? _updateFunc;

    private static readonly string _tag = "StatisticsSingboxService";

    public StatisticsSingboxService(Config config, Func<ServerSpeedItem, Task> updateFunc)
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

        while (!token.IsCancellationRequested)
        {
            try
            {
                if (!AppManager.Instance.IsRunningCore(ECoreType.sing_box))
                {
                    await Task.Delay(1000, token).ConfigureAwait(false);
                    continue;
                }
                var runtime = CoreManager.Instance;
                var session = runtime.SessionId;
                var profileId = runtime.ActiveProfileId;
                if (!runtime.IsRunning || profileId is null) { await Task.Delay(250, token); continue; }
                _traffic.Reset();
                using var ws = new ClientWebSocket();
                ws.Options.Proxy = null;
                using var connectTimeout = CancellationTokenSource.CreateLinkedTokenSource(token);
                connectTimeout.CancelAfter(TimeSpan.FromSeconds(3));
                await ws.ConnectAsync(new Uri($"ws://{Global.Loopback}:{runtime.StatisticsPort}/traffic"), connectTimeout.Token).ConfigureAwait(false);

                var buffer = new byte[1024];
                while (ws.State == WebSocketState.Open
                    && !token.IsCancellationRequested)
                {
                    var res = await ws.ReceiveAsync(new ArraySegment<byte>(buffer), token);
                    if (res.MessageType == WebSocketMessageType.Close)
                    {
                        break;
                    }
                    using var ms = new MemoryStream();
                    ms.Write(buffer, 0, res.Count);
                    while (!res.EndOfMessage)
                    {
                        res = await ws.ReceiveAsync(new ArraySegment<byte>(buffer), token).ConfigureAwait(false);
                        ms.Write(buffer, 0, res.Count);
                    }

                    var result = Encoding.UTF8.GetString(ms.ToArray());
                    if (!result.IsNotEmpty())
                    {
                        continue;
                    }
                    if (!runtime.IsRunning || runtime.SessionId != session) break;
                    ParseOutput(result, out var up, out var down);

                    if (_updateFunc != null)
                    {
                        var sample = _traffic.Add(up, down);
                        await _updateFunc.Invoke(new ServerSpeedItem
                        {
                            IndexId = profileId,
                            ProxyUp = sample.Up,
                            ProxyDown = sample.Down,
                        }).ConfigureAwait(false);
                    }
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

    private void ParseOutput(string source, out ulong up, out ulong down)
    {
        up = 0;
        down = 0;
        try
        {
            var trafficItem = JsonUtils.Deserialize<TrafficItem>(source);
            if (trafficItem != null)
            {
                up = trafficItem.Up;
                down = trafficItem.Down;
            }
        }
        catch
        {
        }
    }
}
