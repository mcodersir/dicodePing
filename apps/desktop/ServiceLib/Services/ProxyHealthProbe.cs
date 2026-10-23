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
        if (!string.IsNullOrWhiteSpace(preferred) && !Global.SpeedPingTestUrls.Contains(preferred, StringComparer.OrdinalIgnoreCase) && !IsLegacyBuiltIn(preferred))
            return [preferred];
        return [string.IsNullOrWhiteSpace(preferred) ? "https://www.gstatic.com/generate_204" : preferred,
            "https://cp.cloudflare.com/generate_204", "https://detectportal.firefox.com/success.txt"];
    }

    private static bool IsLegacyBuiltIn(string url) => Uri.TryCreate(url, UriKind.Absolute, out var uri)
        && uri.Scheme is "http" or "https" && uri.AbsolutePath.TrimEnd('/') == "/generate_204"
        && uri.Host is "www.google.com" or "www.gstatic.com" or "www.youtube.com" or "www.googlevideo.com";

    // One transaction at a time per route. Racing every provider multiplied the
    // scan's TLS/socket load and made slow but usable configs miss their deadline.
    public static async Task<int> MeasureAnyAsync(IEnumerable<string> urls, IWebProxy? proxy, TimeSpan timeout, CancellationToken token = default)
    {
        token.ThrowIfCancellationRequested();
        var targets = urls.Where(x => !string.IsNullOrWhiteSpace(x)).Distinct().ToList();
        using var stop = CancellationTokenSource.CreateLinkedTokenSource(token);
        stop.CancelAfter(timeout);
        var timer = Stopwatch.StartNew();
        for (var i = 0; i < targets.Count; i++)
        {
            var remaining = timeout - timer.Elapsed;
            if (remaining <= TimeSpan.Zero) break;
            var budget = TimeSpan.FromTicks(remaining.Ticks / (targets.Count - i));
            try
            {
                var result = await MeasureAsync(targets[i], proxy, budget, stop.Token);
                if (result > 0) return result;
            }
            catch (OperationCanceledException) when (!token.IsCancellationRequested) { break; }
        }
        token.ThrowIfCancellationRequested();
        return -1;
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
        if (uri.Host.Equals("detectportal.firefox.com", StringComparison.OrdinalIgnoreCase) && uri.AbsolutePath == "/success.txt")
            return status == 200 && body.Trim() == "success";
        return true;
    }
}
