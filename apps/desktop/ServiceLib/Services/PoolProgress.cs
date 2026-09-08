namespace ServiceLib.Services;

public record PoolProgress(string Stage, string Message, int Completed = 0, int Total = 0,
    int Passed = 0, int Failed = 0, int Target = 0);

public sealed record ServerPoolOptions(int TargetCount = 20, int TestRounds = 3)
{
    public const int MinTargetCount = 1;
    public const int MaxTargetCount = 200;
    public const int MinTestRounds = 1;
    public const int MaxTestRounds = 10;

    public ServerPoolOptions Normalize() => new(
        Math.Clamp(TargetCount, MinTargetCount, MaxTargetCount),
        Math.Clamp(TestRounds, MinTestRounds, MaxTestRounds));
}

public static class PoolNetwork
{
    public static readonly string[] ChannelSources =
    [
        ServerPoolService.ChannelsUrl,
        "https://github.com/mcodersir/DicodeConfigChecker/raw/refs/heads/main/channels.txt",
        "https://api.github.com/repos/mcodersir/DicodeConfigChecker/contents/channels.txt"
    ];

    public static async Task WaitForListenerAsync(Func<int> getPort, CancellationToken token, int attempts = 60)
    {
        for (var attempt = 0; attempt < attempts; attempt++)
        {
            token.ThrowIfCancellationRequested();
            try
            {
                using var socket = new System.Net.Sockets.TcpClient();
                using var deadline = CancellationTokenSource.CreateLinkedTokenSource(token);
                deadline.CancelAfter(500);
                await socket.ConnectAsync("127.0.0.1", getPort(), deadline.Token);
                return;
            }
            catch (OperationCanceledException) when (token.IsCancellationRequested) { throw; }
            catch (Exception) { }
            await Task.Delay(500, token);
        }
        throw new IOException("درگاه محلی هسته آماده نشد؛ لاگ اتصال را بررسی کنید.");
    }

    public static string Describe(Exception error) => error switch
    {
        HttpRequestException http when http.StatusCode.HasValue => $"HTTP {(int)http.StatusCode.Value}",
        OperationCanceledException => "پایان مهلت پاسخ",
        HttpRequestException => "خطای شبکه، DNS یا TLS",
        _ => error.GetType().Name
    };

    // Network failures never mean the VPN is disconnected. Keep stage-specific errors.
    public static async Task<List<string>> LoadChannelsAsync(Func<string, CancellationToken, Task<string>> fetch,
        IProgress<PoolProgress> progress, CancellationToken token)
    {
        foreach (var source in ChannelSources)
        {
            for (var attempt = 1; attempt <= 2; attempt++)
            {
                token.ThrowIfCancellationRequested();
                try
                {
                    var channels = ServerPoolService.ParseChannels(await fetch(source, token));
                    if (channels.Count == 0) throw new InvalidDataException("فهرست نامعتبر");
                    progress.Report(new("کانال‌ها", $"فهرست {channels.Count} کانال دریافت شد."));
                    return channels;
                }
                catch (OperationCanceledException) when (token.IsCancellationRequested) { throw; }
                catch (Exception error)
                {
                    progress.Report(new("کانال‌ها", $"دریافت از {new Uri(source).Host} · تلاش {attempt}/۲: {Describe(error)}"));
                    if (attempt == 1) await Task.Delay(750, token);
                }
            }
        }
        throw new IOException("درگاه اتصال آماده است، اما دریافت فهرست کانال‌ها از گیت‌هاب ناموفق بود. دوباره تلاش کنید؛ این خطا به‌معنی قطع VPN نیست.");
    }
}
