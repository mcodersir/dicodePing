namespace ServiceLib.Handler;

public static class ConnectionHandler
{
    private static readonly string _tag = "ConnectionHandler";

    public record SanctionProbeResult(bool Accessible, int Passed, int Total, List<(string Name, bool Ok)> Details);

    public static List<SanctionServiceItem> GetSanctionServices()
    {
        var configured = AppManager.Instance.Config.SanctionsItem?.Services;
        return configured is { Count: > 0 }
            ? configured.Where(s => s.Enabled && s.Name.IsNotEmpty() && s.Url.IsNotEmpty()).ToList()
            : SanctionsDefaults.Services;
    }

    public static SanctionProbeResult TestSanctionsAccess(IWebProxy webProxy)
    {
        return TestSanctionsAccessAsync(webProxy).GetAwaiter().GetResult();
    }

    public static async Task<SanctionProbeResult> TestSanctionsAccessAsync(IWebProxy webProxy, CancellationToken cancellationToken = default)
    {
        var services = GetSanctionServices();
        var timeout = AppManager.Instance.Config.SanctionsItem?.TimeoutSeconds is > 0 and <= 30
            ? AppManager.Instance.Config.SanctionsItem.TimeoutSeconds
            : 9;

        using var handler = new HttpClientHandler
        {
            Proxy = webProxy,
            UseProxy = true,
            AllowAutoRedirect = true,
            AutomaticDecompression = DecompressionMethods.All
        };
        using var client = new HttpClient(handler) { Timeout = TimeSpan.FromSeconds(timeout) };
        client.DefaultRequestHeaders.UserAgent.ParseAdd("DicodePing/4.0 sanctions-probe");

        async Task<(string Name, bool Ok)> Probe(SanctionServiceItem service)
        {
            try
            {
                using var request = new HttpRequestMessage(HttpMethod.Get, service.Url);
                using var response = await client.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, cancellationToken);
                var ok = (int)response.StatusCode is >= 200 and < 500
                    && response.StatusCode != HttpStatusCode.Forbidden
                    && response.StatusCode != HttpStatusCode.UnavailableForLegalReasons;
                return (service.Name, ok);
            }
            catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested) { throw; }
            catch
            {
                return (service.Name, false);
            }
        }

        var details = (await Task.WhenAll(services.Select(Probe))).ToList();
        var total = details.Count;
        var passed = details.Count(d => d.Ok);
        if (total == 0)
        {
            return new SanctionProbeResult(false, 0, 0, []);
        }

        // Strict services (the most reliable sanctions indicators) must pass and
        // the overall pass ratio has to clear two thirds before the exit counts
        // as sanction-free. A single generic success is not enough.
        var strictNames = new HashSet<string>(services.Where(s => s.Strict).Select(s => s.Name), StringComparer.OrdinalIgnoreCase);
        var strictFailed = details.Any(d => !d.Ok && strictNames.Contains(d.Name));
        var accessible = !strictFailed && passed * 3 >= total * 2;
        return new SanctionProbeResult(accessible, passed, total, details);
    }

    /// <summary>
    /// Runs ping and IP checks.
    /// </summary>
    public static async Task<string> RunAvailabilityCheck()
    {
        var result = await RunAvailabilityCheckDetailed();
        return string.Format(ResUI.TestMeOutput, result.Delay, result.Location?.ToString() ?? Global.None);
    }

    public static async Task<(int Delay, IpInfoResult? Location)> RunAvailabilityCheckDetailed()
    {
        if (!CoreManager.Instance.IsRunning) return (-1, null);
        var session = CoreManager.Instance.SessionId;
        var webProxy = await GetWebProxy();
        var ping = GetRealPingTime(webProxy);
        var location = GetIPInfo(webProxy);
        await Task.WhenAll(ping, location);
        return session == CoreManager.Instance.SessionId && CoreManager.Instance.IsRunning
            ? (await ping, await location) : (-1, null);
    }

    /// <summary>
    /// Gets IP information using the default local proxy.
    /// </summary>
    private static async Task<string?> GetIPInfo()
    {
        var webProxy = await GetWebProxy();

        var ipInfo = await GetIPInfo(webProxy);
        return ipInfo?.ToString() ?? Global.None;
    }

    /// <summary>
    /// Measures real ping time using configured test URL.
    /// </summary>
    private static async Task<int> GetRealPingTimeInfo()
    {
        var responseTime = -1;
        try
        {
            var webProxy = await GetWebProxy();

            for (var i = 0; i < 2; i++)
            {
                responseTime = await GetRealPingTime(webProxy);
                if (responseTime > 0)
                {
                    break;
                }
                await Task.Delay(500);
            }
        }
        catch (Exception ex)
        {
            Logging.SaveLog(_tag, ex);
            return -1;
        }
        return responseTime;
    }

    /// <summary>
    /// Creates local SOCKS proxy instance.
    /// </summary>
    private static async Task<WebProxy?> GetWebProxy()
    {
        return CreateActiveProxy();
    }

    public static WebProxy CreateActiveProxy()
    {
        var port = AppManager.Instance.GetLocalPort(EInboundProtocol.socks);
        var proxy = new WebProxy($"socks5://{Global.Loopback}:{port}");
        var inbound = AppManager.Instance.Config.Inbound.FirstOrDefault(x => x.Protocol == nameof(EInboundProtocol.socks));
        if (!string.IsNullOrEmpty(inbound?.User) && !string.IsNullOrEmpty(inbound.Pass))
            proxy.Credentials = new NetworkCredential(inbound.User, inbound.Pass);
        return proxy;
    }

    /// <summary>
    /// Measures response time by sending HTTP requests through proxy.
    /// </summary>
    public static async Task<int> GetRealPingTime(IWebProxy? webProxy, CancellationToken cancellationToken = default)
    {
        return await ProxyHealthProbe.MeasureAnyAsync(new[] { AppManager.Instance.Config.SpeedTestItem.SpeedPingTestUrl,
            "https://cp.cloudflare.com/generate_204", "https://www.gstatic.com/generate_204",
            "https://www.apple.com/library/test/success.html" }, webProxy, TimeSpan.FromSeconds(12), cancellationToken);
    }

    /// <summary>
    /// Gets IP and country information through specified proxy.
    /// </summary>
    public static async Task<IpInfoResult?> GetIPInfo(IWebProxy? webProxy, CancellationToken cancellationToken = default)
    {
        if (webProxy is null) return null;
        using var stop = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        stop.CancelAfter(TimeSpan.FromSeconds(12));
        var urls = Global.IPAPIUrls.Prepend(AppManager.Instance.Config.SpeedTestItem.IPAPIUrl)
            .Where(url => !string.IsNullOrWhiteSpace(url)).Distinct();
        var tasks = urls.Select(async url => {
            try {
                using var handler = new SocketsHttpHandler { Proxy = webProxy, UseProxy = true, AllowAutoRedirect = false };
                var policy = CertPemManager.Instance.BuildCertificateChainPolicy();
                if (policy is not null) handler.SslOptions.CertificateChainPolicy = policy;
                using var client = new HttpClient(handler) { Timeout = TimeSpan.FromSeconds(8), MaxResponseContentBufferSize = 65536 };
                var text = await client.GetStringAsync(url, stop.Token);
                return ParseIPInfo(text);
            } catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested) { throw; }
            catch { return null; }
        }).ToList();
        try {
            while (tasks.Count > 0) {
                var completed = await Task.WhenAny(tasks); tasks.Remove(completed);
                var result = await completed;
                if (result is not null) { stop.Cancel(); return result; }
            }
            cancellationToken.ThrowIfCancellationRequested();
            return null;
        } finally {
            stop.Cancel();
            try { await Task.WhenAll(tasks); } catch (OperationCanceledException) { }
        }
    }

    public static IpInfoResult? ParseIPInfo(string text)
    {
        try {
            var info = JsonUtils.Deserialize<IPAPIInfo>(text);
            if (info is null) return null;
            var ip = new[] { info.ip, info.clientIp, info.ip_addr, info.query }.FirstOrDefault(x => !string.IsNullOrWhiteSpace(x));
            if (!IPAddress.TryParse(ip, out var address) || IPAddress.IsLoopback(address)
                || address.Equals(IPAddress.Any) || address.Equals(IPAddress.IPv6Any)
                || (address.AddressFamily == AddressFamily.InterNetwork && address.GetAddressBytes()[0] is 10 or 127)
                || ip!.StartsWith("198.18.") || ip.StartsWith("198.19.")) return null;
            var country = new[] { info.country_code, info.countryCode, info.location?.country_code, info.country }
                .FirstOrDefault(x => x?.Length == 2 && x.All(char.IsAsciiLetter));
            return country is null ? null : new IpInfoResult(country.ToUpperInvariant(), ip);
        } catch { return null; }
    }
}
