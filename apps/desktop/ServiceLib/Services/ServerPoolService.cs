using System.Globalization;

namespace ServiceLib.Services;

/// <summary>Collects public share links and publishes only independently verified routes.</summary>
public sealed class ServerPoolService
{
    public const string PoolId = "dicode-server-pool";
    public const string PoolName = "سرور های استخر";
    public const string ChannelsUrl = "https://raw.githubusercontent.com/mcodersir/DicodeConfigChecker/refs/heads/main/channels.txt";
    private static readonly SemaphoreSlim Gate = new(1, 1);
    private static readonly TimeSpan RegexTimeout = TimeSpan.FromSeconds(1);
    private static readonly Regex Links = new(@"(?i)\b(?:vmess|vless|trojan|ss)://[^\s<>""'`\u200b-\u200f]+", RegexOptions.None, RegexTimeout);
    private static readonly Regex MessageWrappers = new("""<div\b[^>]*\bclass\s*=\s*["'][^"']*\btgme_widget_message_wrap\b[^"']*["'][^>]*>""", RegexOptions.IgnoreCase, RegexTimeout);
    private static readonly Regex Dates = new("""\bdatetime\s*=\s*["']([^"']+)["']""", RegexOptions.IgnoreCase, RegexTimeout);
    private static readonly Regex Hrefs = new("""\bhref\s*=\s*["']([^"']+)["']""", RegexOptions.IgnoreCase, RegexTimeout);

    private sealed class PreparedRoute(HttpClient client, List<string> channels, string name) : IDisposable
    {
        public HttpClient Client { get; } = client;
        public List<string> Channels { get; } = channels;
        public string Name { get; } = name;
        public void Dispose() => Client.Dispose();
    }

    public static List<string> ParseChannels(string content) => content.Split('\n')
        .Select(x => x.Trim().Replace("https://t.me/", "").Replace("http://t.me/", "").Replace("t.me/", "").TrimStart('@').TrimEnd('/'))
        .Where(x => Regex.IsMatch(x, @"^[a-zA-Z][a-zA-Z0-9_]{3,31}$", RegexOptions.None, RegexTimeout))
        .Distinct(StringComparer.OrdinalIgnoreCase).Take(500).ToList();

    public sealed record Extraction(List<string> Links, int Posts, int DatedPosts, DateTimeOffset? Newest)
    {
        public string Summary => Links.Count > 0
            ? Newest.HasValue
                ? $"{Links.Count} کاندید از آخرین پیام‌های قابل‌نمایش · تاریخ {Newest:yyyy-MM-dd}"
                : $"{Links.Count} کاندید از آخرین پیام‌های قابل‌نمایش · تاریخ در HTML نبود"
            : Posts == 0 ? "صفحهٔ پیام‌های عمومی دریافت نشد"
            : DatedPosts == 0 ? $"{Posts} پیام؛ بدون لینک مستقیم V2Ray · تاریخ در HTML نبود"
            : $"{Posts} پیام؛ بدون لینک مستقیم V2Ray";
    }

    public static Extraction Inspect(string html)
    {
        if (string.IsNullOrWhiteSpace(html)) return new([], 0, 0, null);

        var posts = MessageWrappers.Split(html).Skip(1).ToList();
        var datedPosts = 0;
        DateTimeOffset? newest = null;
        var links = new List<string>(4);

        bool AddLinks(string fragment)
        {
            var hrefs = Hrefs.Matches(fragment).Select(match => match.Groups[1].Value);
            var text = Regex.Replace(fragment,
                @"</?(?:div|p|pre|li|code|time|blockquote|section|article)\b[^>]*>|<br\s*/?>",
                "\n", RegexOptions.IgnoreCase, RegexTimeout);
            text = Regex.Replace(text, "<[^>]+>", "", RegexOptions.None, RegexTimeout);
            var normalized = WebUtility.HtmlDecode(string.Join("\n", hrefs) + "\n" + text)
                .Replace("\\u0026", "&", StringComparison.OrdinalIgnoreCase);
            foreach (var match in Links.Matches(normalized).Cast<Match>().Reverse())
            {
                var link = match.Value.TrimEnd(')', ']', '}', ',', ';', '.', '،');
                if (FmtHandler.ResolveConfig(link, out _) is null || links.Contains(link, StringComparer.Ordinal)) continue;
                links.Add(link);
                if (links.Count == 4) return true;
            }
            return false;
        }

        // Public previews may omit datetime. Source order is still oldest-to-newest, so walk
        // message bodies in reverse and treat the timestamp as optional reporting metadata.
        foreach (var post in posts.AsEnumerable().Reverse())
        {
            var dateMatch = Dates.Match(post);
            DateTimeOffset? timestamp = DateTimeOffset.TryParse(dateMatch.Groups[1].Value,
                CultureInfo.InvariantCulture, DateTimeStyles.None, out var parsed) ? parsed : null;
            if (timestamp.HasValue) datedPosts++;
            var countBefore = links.Count;
            var full = AddLinks(post);
            if (links.Count > countBefore && !newest.HasValue) newest = timestamp;
            if (full) break;
        }

        // Some embedded/fallback pages expose configs but not the legacy message wrapper.
        if (posts.Count == 0 && AddLinks(html)) newest = null;
        var postCount = posts.Count == 0 && links.Count > 0 ? 1 : posts.Count;
        return new(links, postCount, datedPosts, newest);
    }

    public static List<string> ExtractLinks(string html) => Inspect(html).Links;

    public static async Task EnsureSubscriptionAsync()
    {
        var item = await AppManager.Instance.GetSubItem(PoolId) ?? new SubItem { Id = PoolId };
        item.Remarks = PoolName; item.Url = ""; item.Enabled = true; item.AutoUpdateInterval = 0;
        if (await ConfigHandler.AddSubItem(AppManager.Instance.Config, item) != 0)
            throw new IOException("ساخت اشتراک سرور های استخر ناموفق بود.");
    }

    public static bool AcceptSamples(IReadOnlyList<int> samples, int requiredRounds = 3) =>
        requiredRounds is >= ServerPoolOptions.MinTestRounds and <= ServerPoolOptions.MaxTestRounds
        && samples.Count == requiredRounds
        && samples.All(x => x > 0 && x <= 900);

    private static HttpClient Client(IWebProxy? proxy, int timeoutSeconds = 15) => new(new SocketsHttpHandler
    {
        Proxy = proxy, UseProxy = proxy != null, ConnectTimeout = TimeSpan.FromSeconds(Math.Min(5, timeoutSeconds)),
        AutomaticDecompression = DecompressionMethods.All
    }) { Timeout = TimeSpan.FromSeconds(timeoutSeconds), MaxResponseContentBufferSize = 2 * 1024 * 1024 };

    private static void ConfigureBrowserHeaders(HttpClient client)
    {
        client.DefaultRequestHeaders.UserAgent.ParseAdd("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128 Safari/537.36 DicodePing/4.0.0");
        client.DefaultRequestHeaders.AcceptLanguage.ParseAdd("en-US,en;q=0.8,fa;q=0.7");
    }

    private static WebProxy LocalProxy(Config config)
    {
        var proxy = new WebProxy($"socks5://{Global.Loopback}:{AppManager.Instance.GetLocalPort(EInboundProtocol.socks)}");
        var inbound = config.Inbound.FirstOrDefault();
        if (!string.IsNullOrEmpty(inbound?.User)) proxy.Credentials = new NetworkCredential(inbound.User, inbound.Pass);
        return proxy;
    }

    private static async Task<string> FetchAsync(HttpClient client, string url, CancellationToken token)
    {
        using var request = new HttpRequestMessage(HttpMethod.Get, url);
        request.Headers.Accept.ParseAdd(url.StartsWith("https://api.github.com/", StringComparison.OrdinalIgnoreCase)
            ? "application/vnd.github.raw+json"
            : "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.8");
        using var response = await client.SendAsync(request, token);
        response.EnsureSuccessStatusCode();
        return await response.Content.ReadAsStringAsync(token);
    }

    private static async Task<PreparedRoute?> TryPrepareRouteAsync(string name, IWebProxy? proxy,
        IProgress<PoolProgress> progress, CancellationToken token)
    {
        var client = Client(proxy, 8);
        ConfigureBrowserHeaders(client);
        try
        {
            progress.Report(new("مسیر فعال", $"بررسی {name} بدون تغییر اتصال فعلی…"));
            List<string>? channels = null;
            foreach (var source in PoolNetwork.ChannelSources)
            {
                token.ThrowIfCancellationRequested();
                try
                {
                    channels = ParseChannels(await FetchAsync(client, source, token));
                    if (channels.Count > 0) break;
                }
                catch (OperationCanceledException) when (token.IsCancellationRequested) { throw; }
                catch { }
            }
            if (channels is null || channels.Count == 0) throw new IOException("فهرست کانال‌ها در دسترس نیست");

            async Task<bool> CanReadChannel(string channel)
            {
                try
                {
                    var extraction = Inspect(await FetchAsync(client, $"https://t.me/s/{channel}", token));
                    if (extraction.Posts == 0)
                        extraction = Inspect(await FetchAsync(client, $"https://telegram.me/s/{channel}", token));
                    return extraction.Posts > 0;
                }
                catch (OperationCanceledException) when (token.IsCancellationRequested) { throw; }
                catch { return false; }
            }

            var telegramChecks = await Task.WhenAll(channels.Take(5).Select(CanReadChannel));
            if (!telegramChecks.Any(x => x)) throw new IOException("Telegram preview در دسترس نیست");
            progress.Report(new("مسیر فعال", $"{name} قابل استفاده است؛ اتصال کاربر تغییر نمی‌کند."));
            return new PreparedRoute(client, channels, name);
        }
        catch (OperationCanceledException) when (token.IsCancellationRequested)
        {
            client.Dispose();
            throw;
        }
        catch
        {
            client.Dispose();
            progress.Report(new("مسیر فعال", $"{name} برای هر دو منبع GitHub و Telegram قابل استفاده نبود."));
            return null;
        }
    }

    public async Task<int> RunAsync(Func<ProfileItem, CancellationToken, Task> connect,
        IProgress<PoolProgress> progress, ServerPoolOptions requestedOptions,
        CancellationToken stopToken, CancellationToken abortToken)
    {
        if (!await Gate.WaitAsync(0, abortToken)) throw new InvalidOperationException("جمع‌آوری دیگری در حال اجراست.");
        var options = requestedOptions.Normalize();
        using var preparation = CancellationTokenSource.CreateLinkedTokenSource(stopToken, abortToken);
        var preparationToken = preparation.Token;
        var config = AppManager.Instance.Config;
        try
        {
            await EnsureSubscriptionAsync();
            progress.Report(new("استخر", $"اشتراک مستقل «{PoolName}» آماده است."));
            var route = await TryPrepareRouteAsync("اتصال فعال DicodePing", LocalProxy(config), progress, preparationToken)
                ?? await TryPrepareRouteAsync("مسیر مستقیم سیستم یا VPN دیگر", null, progress, preparationToken);
            if (route is null)
            {
                progress.Report(new("ساب پیش‌فرض", "مسیر فعالی برای Telegram پیدا نشد؛ آزمون ساب پیش‌فرض…"));
                await DicodePingBootstrap.EnsureDefaultsAsync(config);
                var primary = (await AppManager.Instance.SubItems())!.First(x => x.Url == DicodePingBootstrap.DefaultSubscriptionUrl);
                var subscriptionUpdated = false;
                try
                {
                    await SubscriptionHandler.UpdateProcess(config, primary.Id, false, (success, _) =>
                    {
                        if (success) subscriptionUpdated = true;
                        return Task.CompletedTask;
                    });
                    if (!subscriptionUpdated)
                        progress.Report(new("ساب پیش‌فرض", "بروزرسانی ساب نتیجه‌ای نداشت؛ cache موجود آزموده می‌شود."));
                }
                catch (Exception error)
                {
                    progress.Report(new("ساب پیش‌فرض", $"بروزرسانی ساب در دسترس نبود ({PoolNetwork.Describe(error)})؛ cache موجود آزموده می‌شود."));
                }
                preparationToken.ThrowIfCancellationRequested();
                var initialProfiles = await AppManager.Instance.ProfileItems(primary.Id) ?? [];
                var initial = await ProbeAsync(initialProfiles, 1, initialProfiles.Count, false, progress,
                    preparationToken, CancellationToken.None);
                var best = initial.OrderBy(x => x.Delay).FirstOrDefault();
                if (best.Profile == null) throw new InvalidOperationException("هیچ مسیر فعال یا کانفیگ سالمی در cache ساب پیش‌فرض پیدا نشد؛ دوباره تلاش کنید.");
                progress.Report(new("اتصال", $"شروع اتصال fallback به بهترین مسیر ساب پیش‌فرض · {best.Delay} ms"));
                await connect(best.Profile, preparationToken);
                preparationToken.ThrowIfCancellationRequested();
                route = await TryPrepareRouteAsync("مسیر fallback ساب پیش‌فرض", LocalProxy(config), progress, preparationToken)
                    ?? throw new InvalidOperationException("اتصال fallback برقرار شد اما GitHub و Telegram از آن قابل دسترسی نیستند.");
            }
            using (route)
            {
            var client = route.Client;
            var channels = route.Channels;
            progress.Report(new("کانال‌ها", $"فهرست {channels.Count} کانال از {route.Name} آماده است."));
            var collected = new ConcurrentDictionary<string, byte>();
            int completed = 0, failed = 0;
            await Parallel.ForEachAsync(channels, new ParallelOptions { MaxDegreeOfParallelism = 8, CancellationToken = preparationToken }, async (channel, ct) =>
            {
                try
                {
                    var extraction = Inspect(await FetchAsync(client, $"https://t.me/s/{channel}", ct));
                    if (extraction.Posts == 0)
                    {
                        extraction = Inspect(await FetchAsync(client, $"https://telegram.me/s/{channel}", ct));
                    }
                    if (extraction.Posts == 0) Interlocked.Increment(ref failed);
                    foreach (var link in extraction.Links) collected.TryAdd(link, 0);
                    progress.Report(new("جمع‌آوری", $"@{channel} · {extraction.Summary}"));
                }
                catch (OperationCanceledException) when (ct.IsCancellationRequested) { throw; }
                catch (Exception error) { Interlocked.Increment(ref failed); progress.Report(new("جمع‌آوری", $"@{channel} · {PoolNetwork.Describe(error)}")); }
                progress.Report(new("جمع‌آوری", $"کانفیگ یکتا: {collected.Count}", Interlocked.Increment(ref completed), channels.Count, collected.Count, failed));
            });
            var profiles = collected.Keys.Select(x => FmtHandler.ResolveConfig(x, out _)).OfType<ProfileItem>().ToList();
            if (profiles.Count == 0) throw new InvalidOperationException("از پیام‌های قابل‌دسترسی هیچ کانفیگ V2Ray استخراج نشد؛ آزمون آغاز نشد. جزئیات کانال‌ها را در لاگ بررسی کنید؛ استخر قبلی حفظ شد.");
            foreach (var profile in profiles) { profile.IndexId = Utils.GetGuid(false); profile.Subid = PoolId; }
            progress.Report(new("آزمون",
                $"{profiles.Count} کانفیگ قابل آزمون · هدف {options.TargetCount} سرور موفق · {options.TestRounds} نوبت تست واقعی همزمان",
                0, profiles.Count, 0, 0, options.TargetCount));
            var accepted = await ProbeAsync(profiles, options.TestRounds, options.TargetCount, true,
                progress, abortToken, stopToken);
            abortToken.ThrowIfCancellationRequested();
            var stopped = stopToken.IsCancellationRequested;
            if (accepted.Count == 0)
            {
                if (stopped) throw new OperationCanceledException(stopToken);
                throw new InvalidOperationException("کانفیگ واجد شرایط پیدا نشد؛ استخر قبلی حفظ شد.");
            }
            progress.Report(new("ذخیره", stopped
                ? $"توقف انجام شد؛ ذخیرهٔ {accepted.Count} سرور موفق تکمیل‌شده…"
                : $"ذخیرهٔ {accepted.Count} کانفیگ تأییدشده…", Passed: accepted.Count, Target: options.TargetCount));
            await ProfileOperationCoordinator.Gate.WaitAsync(abortToken);
            try
            {
                await EnsureSubscriptionAsync();
                await SQLiteHelper.Instance.ReplaceServerPoolAsync(PoolId, accepted.OrderBy(x => x.Delay).Select(x => x.Profile).ToList(), config.IndexId);
                foreach (var item in accepted) ProfileExManager.Instance.SetTestDelay(item.Profile.IndexId, item.Delay);
                await ProfileExManager.Instance.SaveTo();
            }
            finally { ProfileOperationCoordinator.Gate.Release(); }
            progress.Report(new(stopped ? "متوقف" : "پایان",
                stopped
                    ? $"آزمایش با درخواست شما متوقف شد و {accepted.Count} سرور موفق در استخر ذخیره شد."
                    : $"{accepted.Count} کانفیگ سالم در استخر ذخیره شد.",
                accepted.Count, accepted.Count, accepted.Count, 0, options.TargetCount));
            return accepted.Count;
            }
        }
        finally { Gate.Release(); }
    }

    private static async Task<List<(ProfileItem Profile, int Delay)>> ProbeAsync(List<ProfileItem> profiles,
        int rounds, int targetCount, bool strict, IProgress<PoolProgress> progress,
        CancellationToken abortToken, CancellationToken gracefulStopToken)
    {
        var result = new ConcurrentDictionary<string, (ProfileItem Profile, int Delay)>();
        var acceptedCount = 0;
        var done = 0;
        var pending = new Queue<ProfileItem[]>(profiles.Chunk(12));
        while (pending.TryDequeue(out var chunk))
        {
            abortToken.ThrowIfCancellationRequested();
            if ((strict && gracefulStopToken.IsCancellationRequested) || result.Count >= targetCount) break;
            var baseIndex = done;
            var batch = chunk.Select((p, i) => new ServerTestItem { IndexId = p.IndexId, Address = p.Address,
                Port = p.Port, ConfigType = p.ConfigType, Profile = p, QueueNum = i,
                CoreType = AppManager.Instance.GetCoreType(p, p.ConfigType) }).ToList();
            var core = await CoreManager.Instance.LoadCoreConfigSpeedtest(batch);
            if (core == null)
            {
                progress.Report(new("آزمون", "هستهٔ این دسته آماده نشد؛ جداسازی کانفیگ ناسازگار…"));
                if (chunk.Length == 1)
                {
                    var rejected = Interlocked.Increment(ref done);
                    progress.Report(new("آزمون", "کانفیگ ناسازگار با هسته رد شد؛ سایر سرورها بررسی می‌شوند.",
                        rejected, profiles.Count, result.Count, Math.Max(0, rejected - result.Count), strict ? targetCount : 0));
                }
                else
                {
                    var midpoint = chunk.Length / 2;
                    pending.Enqueue(chunk[..midpoint]);
                    pending.Enqueue(chunk[midpoint..]);
                }
                continue;
            }
            try
            {
                using var testRun = CancellationTokenSource.CreateLinkedTokenSource(abortToken, gracefulStopToken);
                var testToken = strict ? testRun.Token : abortToken;
                await Task.Delay(800, testToken);
                if (core.HasExited)
                {
                    if (chunk.Length == 1)
                    {
                        var rejected = Interlocked.Increment(ref done);
                        progress.Report(new("آزمون", "هستهٔ کانفیگ پیش از آزمون بسته شد و سرور رد شد.",
                            rejected, profiles.Count, result.Count, Math.Max(0, rejected - result.Count), strict ? targetCount : 0));
                    }
                    else
                    {
                        var midpoint = chunk.Length / 2;
                        pending.Enqueue(chunk[..midpoint]);
                        pending.Enqueue(chunk[midpoint..]);
                    }
                    continue;
                }
                await Parallel.ForEachAsync(batch, new ParallelOptions { MaxDegreeOfParallelism = 6, CancellationToken = testToken }, async (item, ct) =>
                {
                    var samples = new List<int>();
                    try
                    {
                        if (!item.AllowTest || (strict && result.Count >= targetCount)) return;
                        var ready = true;
                        try { await PoolNetwork.WaitForListenerAsync(() => item.Port, ct, 10); }
                        catch (IOException) { ready = false; progress.Report(new("آزمون", $"سرور {baseIndex + item.QueueNum + 1} · درگاه هستهٔ آزمون آماده نشد")); }
                        var webProxy = new WebProxy($"socks5://{Global.Loopback}:{item.Port}");
                        for (var round = 0; round < rounds; round++)
                        {
                            ct.ThrowIfCancellationRequested();
                            if (!ready) { samples.Add(-1); continue; }
                            // Use the exact same SOCKS/HTTP real-latency engine as the main
                            // Real Ping action (including its two-request stabilization).
                            var delay = await ConnectionHandler.GetRealPingTime(webProxy, strict ? 4 : 8);
                            ct.ThrowIfCancellationRequested();
                            samples.Add(delay);
                            progress.Report(new(strict ? "آزمون" : "ساب پیش‌فرض",
                                $"سرور {baseIndex + item.QueueNum + 1} · نوبت {round + 1}/{rounds}: {(delay > 0 ? $"{delay} ms" : "ناموفق")}",
                                Passed: result.Count, Target: strict ? targetCount : 0));
                        }
                        var accepted = strict ? AcceptSamples(samples, rounds) : samples.Count == rounds && samples.All(x => x > 0);
                        if (accepted)
                        {
                            var reservation = Interlocked.Increment(ref acceptedCount);
                            if (reservation <= targetCount)
                                result.TryAdd(item.Profile.IndexId, (item.Profile, samples.Order().ElementAt(samples.Count / 2)));
                        }
                        progress.Report(new(strict ? "آزمون" : "ساب پیش‌فرض",
                            $"سرور {item.QueueNum + baseIndex + 1} · پاسخ‌ها: {string.Join(" / ", samples.Select(x => x > 0 ? $"{x} ms" : "ناموفق"))} · {(accepted ? "پذیرفته" : "رد شد")}",
                            Passed: result.Count, Target: strict ? targetCount : 0));
                    }
                    finally
                    {
                        var tested = Interlocked.Increment(ref done);
                        progress.Report(new(strict ? "آزمون" : "ساب پیش‌فرض",
                            strict ? $"آزمون واقعی مسیر · موفق {result.Count}/{targetCount}" : "آزمون واقعی مسیر",
                            tested, profiles.Count, result.Count, Math.Max(0, tested - result.Count), strict ? targetCount : 0));
                    }
                });
            }
            catch (OperationCanceledException) when (strict && gracefulStopToken.IsCancellationRequested && !abortToken.IsCancellationRequested)
            {
                break;
            }
            finally { await core.StopAsync(); core.Dispose(); }
        }
        return result.Values.OrderBy(x => x.Delay).Take(targetCount).ToList();
    }
}
