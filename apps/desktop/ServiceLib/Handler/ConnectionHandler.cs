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
        var time = await GetRealPingTimeInfo();
        var webProxy = time > 0 ? await GetWebProxy() : null;
        var location = time > 0 ? await GetIPInfo(webProxy) : null;
        return (time, location);
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
        var port = AppManager.Instance.GetLocalPort(EInboundProtocol.socks);
        return new WebProxy($"socks5://{Global.Loopback}:{port}");
    }

    /// <summary>
    /// Measures response time by sending HTTP requests through proxy.
    /// </summary>
    public static async Task<int> GetRealPingTime(IWebProxy? webProxy, CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        var url = AppManager.Instance.Config.SpeedTestItem.SpeedPingTestUrl;
        var responseTime = -1;
        try
        {
            using var timeoutCts = new CancellationTokenSource();
            timeoutCts.CancelAfter(Global.LocalFetch);
            using var linkedCts = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken, timeoutCts.Token);
            var linkedToken = linkedCts.Token;
            using var client = new HttpClient(new SocketsHttpHandler()
            {
                Proxy = webProxy,
                UseProxy = webProxy != null,
                ConnectTimeout = Global.LocalFetch,
            });

            List<int> oneTime = [];
            for (var i = 0; i < 2; i++)
            {
                var timer = Stopwatch.StartNew();
                await client.GetAsync(url, linkedToken).ConfigureAwait(false);
                timer.Stop();
                oneTime.Add((int)timer.Elapsed.TotalMilliseconds);
                await Task.Delay(100, linkedToken);
            }
            responseTime = oneTime.Where(x => x > 0).OrderBy(x => x).FirstOrDefault();
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            throw;
        }
        catch
        {
            // Ignore
        }
        return responseTime;
    }

    /// <summary>
    /// Gets IP and country information through specified proxy.
    /// </summary>
    public static async Task<IpInfoResult?> GetIPInfo(IWebProxy? webProxy, CancellationToken cancellationToken = default)
    {
        try
        {
            var downloadHandle = new DownloadService();
            var preferredUrl = AppManager.Instance.Config.SpeedTestItem.IPAPIUrl;
            // Some IP APIs are intermittently blocked. Try the configured API
            // first, then the product's supported fallbacks through the same
            // temporary proxy; this is especially important for the beta
            // location action and never touches the saved ping value.
            var urls = Global.IPAPIUrls
                .Prepend(preferredUrl)
                .Where(url => url.IsNotEmpty())
                .Distinct();
            foreach (var url in urls)
            {
                var result = await downloadHandle.TryDownloadString(url, webProxy, "", cancellationToken);
                var ipInfo = result.IsNotEmpty() ? JsonUtils.Deserialize<IPAPIInfo>(result) : null;
                if (ipInfo == null)
                {
                    continue;
                }
                var ip = ipInfo.ip ?? ipInfo.clientIp ?? ipInfo.ip_addr ?? ipInfo.query;
                var country = ipInfo.country_code ?? ipInfo.country ?? ipInfo.countryCode ?? ipInfo.location?.country_code;
                if (country.IsNotEmpty())
                {
                    return new IpInfoResult(country, ip);
                }
            }
            return null;
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            throw;
        }
        catch
        {
            return null;
        }
    }
}
