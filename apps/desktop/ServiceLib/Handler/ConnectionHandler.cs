namespace ServiceLib.Handler;

public static class ConnectionHandler
{
    private static readonly string _tag = "ConnectionHandler";
    private static readonly string[] SanctionsProbeUrls =
    [
        "https://gemini.google.com/",
        "https://flow.google/",
        "https://firebase.google.com/",
        "https://dart.dev/",
        "https://flutter.dev/"
    ];

    public static async Task<(bool Accessible, int Passed, int Total)> TestSanctionsAccess(IWebProxy webProxy)
    {
        using var handler = new HttpClientHandler
        {
            Proxy = webProxy,
            UseProxy = true,
            AllowAutoRedirect = true,
            AutomaticDecompression = DecompressionMethods.All
        };
        using var client = new HttpClient(handler) { Timeout = TimeSpan.FromSeconds(9) };
        client.DefaultRequestHeaders.UserAgent.ParseAdd("DicodePing/3.0 sanctions-probe");

        async Task<bool> Probe(string url)
        {
            try
            {
                using var request = new HttpRequestMessage(HttpMethod.Get, url);
                using var response = await client.SendAsync(request, HttpCompletionOption.ResponseHeadersRead);
                return (int)response.StatusCode is >= 200 and < 500
                    && response.StatusCode != HttpStatusCode.Forbidden
                    && response.StatusCode != HttpStatusCode.UnavailableForLegalReasons;
            }
            catch
            {
                return false;
            }
        }

        var results = await Task.WhenAll(SanctionsProbeUrls.Select(Probe));
        var passed = results.Count(value => value);
        // At least one restricted Google AI surface and most developer surfaces
        // must be reachable; a single generic Google response is not enough.
        return ((results[0] || results[1]) && passed >= 3, passed, results.Length);
    }

    /// <summary>
    /// Runs ping and IP checks and returns a formatted result string.
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
    public static async Task<int> GetRealPingTime(IWebProxy? webProxy, int downloadTimeout = 9)
    {
        var url = AppManager.Instance.Config.SpeedTestItem.SpeedPingTestUrl;
        var responseTime = -1;
        try
        {
            using var cts = new CancellationTokenSource();
            cts.CancelAfter(TimeSpan.FromSeconds(downloadTimeout));
            using var client = new HttpClient(new SocketsHttpHandler()
            {
                Proxy = webProxy,
                UseProxy = webProxy != null,
                ConnectTimeout = TimeSpan.FromSeconds(3)
            });

            List<int> oneTime = [];
            for (var i = 0; i < 2; i++)
            {
                var timer = Stopwatch.StartNew();
                await client.GetAsync(url, cts.Token).ConfigureAwait(false);
                timer.Stop();
                oneTime.Add((int)timer.Elapsed.TotalMilliseconds);
                await Task.Delay(100, cts.Token);
            }
            responseTime = oneTime.Where(x => x > 0).OrderBy(x => x).FirstOrDefault();
        }
        catch
        {
        }
        return responseTime;
    }

    /// <summary>
    /// Gets IP and country information through specified proxy.
    /// </summary>
    public static async Task<IpInfoResult?> GetIPInfo(IWebProxy? webProxy)
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
                var result = await downloadHandle.TryDownloadString(url, webProxy, "");
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
        catch
        {
            return null;
        }
    }
}
