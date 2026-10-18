namespace ServiceLib.Services;

/// <summary>A bounded HTTP transaction through the requested proxy, with no direct fallback.</summary>
public static class ProxyHealthProbe
{
    public static async Task<int> MeasureAsync(string url, IWebProxy? proxy, TimeSpan timeout, CancellationToken token = default)
    {
        token.ThrowIfCancellationRequested();
        if (proxy is null || !Uri.TryCreate(url, UriKind.Absolute, out var uri)
            || uri.Scheme is not ("http" or "https") || proxy.IsBypassed(uri)) return -1;
        using var deadline = CancellationTokenSource.CreateLinkedTokenSource(token);
        deadline.CancelAfter(timeout);
        var handler = new SocketsHttpHandler
        {
            Proxy = proxy, UseProxy = true, AllowAutoRedirect = false,
            ConnectTimeout = timeout,
        };
        var policy = CertPemManager.Instance.BuildCertificateChainPolicy();
        if (policy is not null) handler.SslOptions.CertificateChainPolicy = policy;
        using var client = new HttpClient(handler) { Timeout = timeout, MaxResponseContentBufferSize = 65536 };
        var best = int.MaxValue;
        try
        {
            for (var i = 0; i < 2; i++)
            {
                using var request = new HttpRequestMessage(HttpMethod.Get, uri);
                request.Headers.CacheControl = new() { NoCache = true, NoStore = true };
                var timer = Stopwatch.StartNew();
                using var response = await client.SendAsync(request, deadline.Token).ConfigureAwait(false);
                var body = await response.Content.ReadAsStringAsync(deadline.Token).ConfigureAwait(false);
                if (!IsExpectedResponse(uri, (int)response.StatusCode, body)) break;
                best = Math.Min(best, Math.Max(1, (int)timer.Elapsed.TotalMilliseconds));
            }
            return best == int.MaxValue ? -1 : best;
        }
        catch (OperationCanceledException) when (token.IsCancellationRequested) { throw; }
        catch { return best == int.MaxValue ? -1 : best; }
    }

    public static IReadOnlyList<string> TargetsFor(string preferred)
    {
        // A user-supplied endpoint is an exact diagnostic, not permission to test other sites.
        if (!string.IsNullOrWhiteSpace(preferred) && !Global.SpeedPingTestUrls.Contains(preferred, StringComparer.OrdinalIgnoreCase))
            return [preferred];
        return [preferred, "https://cp.cloudflare.com/generate_204", "https://www.gstatic.com/generate_204",
            "https://www.apple.com/library/test/success.html"];
    }

    // Independent providers share one deadline. Every request uses the same explicit proxy.
    public static async Task<int> MeasureAnyAsync(IEnumerable<string> urls, IWebProxy? proxy, TimeSpan timeout, CancellationToken token = default)
    {
        token.ThrowIfCancellationRequested();
        using var stop = CancellationTokenSource.CreateLinkedTokenSource(token);
        stop.CancelAfter(timeout);
        var pending = urls.Where(x => !string.IsNullOrWhiteSpace(x)).Distinct().Select(async url =>
        {
            try { return await MeasureAsync(url, proxy, timeout, stop.Token); }
            catch (OperationCanceledException) when (!token.IsCancellationRequested) { return -1; }
        }).ToList();
        try {
            while (pending.Count > 0) {
                var completed = await Task.WhenAny(pending);
                pending.Remove(completed);
                var result = await completed;
                if (result > 0) { stop.Cancel(); return result; }
            }
            token.ThrowIfCancellationRequested();
            return -1;
        } finally {
            stop.Cancel();
            // Observe and dispose every losing request before its test core is stopped.
            try { await Task.WhenAll(pending); } catch (OperationCanceledException) { }
        }
    }

    public static bool IsExpectedResponse(Uri uri, int status, string body)
    {
        if (status is < 200 or >= 300) return false;
        if (uri.AbsolutePath.TrimEnd('/').EndsWith("generate_204", StringComparison.OrdinalIgnoreCase))
            return status == 204 && body.Length == 0;
        if (uri.Host.Equals("www.msftconnecttest.com", StringComparison.OrdinalIgnoreCase) && uri.AbsolutePath == "/connecttest.txt")
            return status == 200 && body.Trim() == "Microsoft Connect Test";
        if (uri.Host.Equals("www.apple.com", StringComparison.OrdinalIgnoreCase) && uri.AbsolutePath == "/library/test/success.html")
            return status == 200 && body.Contains("<TITLE>Success</TITLE>", StringComparison.OrdinalIgnoreCase);
        return true;
    }
}
