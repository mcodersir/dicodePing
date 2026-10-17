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
        using var client = new HttpClient(new SocketsHttpHandler
        {
            Proxy = proxy, UseProxy = true, AllowAutoRedirect = false,
            ConnectTimeout = timeout,
        }) { Timeout = timeout, MaxResponseContentBufferSize = 65536 };
        try
        {
            var best = int.MaxValue;
            for (var i = 0; i < 2; i++)
            {
                using var request = new HttpRequestMessage(HttpMethod.Get, uri);
                request.Headers.CacheControl = new() { NoCache = true, NoStore = true };
                var timer = Stopwatch.StartNew();
                using var response = await client.SendAsync(request, deadline.Token).ConfigureAwait(false);
                var body = await response.Content.ReadAsStringAsync(deadline.Token).ConfigureAwait(false);
                if (!IsExpectedResponse(uri, (int)response.StatusCode, body)) return -1;
                best = Math.Min(best, Math.Max(1, (int)timer.Elapsed.TotalMilliseconds));
            }
            return best;
        }
        catch (OperationCanceledException) when (token.IsCancellationRequested) { throw; }
        catch { return -1; }
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
