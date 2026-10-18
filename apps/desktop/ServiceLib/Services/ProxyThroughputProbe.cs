namespace ServiceLib.Services;

public static class ProxyThroughputProbe
{
    // MB/s from payload bytes, not the requested file size or HTTP headers.
    public static async Task<decimal> MeasureAsync(IEnumerable<string> urls, IWebProxy proxy, TimeSpan duration, CancellationToken token = default)
    {
        foreach (var url in urls.Where(x => !string.IsNullOrWhiteSpace(x)).Distinct())
        {
            token.ThrowIfCancellationRequested();
            using var handler = new SocketsHttpHandler { Proxy = proxy, UseProxy = true, AllowAutoRedirect = false };
            var policy = CertPemManager.Instance.BuildCertificateChainPolicy();
            if (policy is not null) handler.SslOptions.CertificateChainPolicy = policy;
            using var client = new HttpClient(handler) { Timeout = Timeout.InfiniteTimeSpan };
            using var stop = CancellationTokenSource.CreateLinkedTokenSource(token);
            stop.CancelAfter(duration);
            long bytes = 0;
            var timer = new Stopwatch();
            try
            {
                using var request = new HttpRequestMessage(HttpMethod.Get, url);
                request.Headers.CacheControl = new() { NoCache = true, NoStore = true };
                request.Headers.AcceptEncoding.ParseAdd("identity");
                using var response = await client.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, stop.Token);
                response.EnsureSuccessStatusCode();
                if (response.Content.Headers.ContentType?.MediaType is "text/html" or "application/json") continue;
                await using var stream = await response.Content.ReadAsStreamAsync(stop.Token);
                var buffer = new byte[65536];
                timer.Start();
                while (true) {
                    var count = await stream.ReadAsync(buffer, stop.Token);
                    if (count == 0) break;
                    bytes += count;
                }
            }
            catch (OperationCanceledException) when (token.IsCancellationRequested) { throw; }
            catch (OperationCanceledException) { /* A bounded payload sample. */ }
            catch { bytes = 0; }
            finally { timer.Stop(); }
            if (bytes >= 65536 && timer.Elapsed.TotalSeconds > 0)
                return Math.Round((decimal)(bytes / timer.Elapsed.TotalSeconds / 1_000_000), 2);
        }
        token.ThrowIfCancellationRequested();
        return 0;
    }
}
