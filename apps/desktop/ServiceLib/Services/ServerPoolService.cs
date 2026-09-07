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
    private static readonly Regex Links = new(@"(?i)\b(?:vmess|vless|trojan|ss)://[^\s<>""'\u200b-\u200f]+", RegexOptions.None, RegexTimeout);

    public static List<string> ParseChannels(string content) => content.Split('\n')
        .Select(x => x.Trim().Replace("https://t.me/", "").Replace("http://t.me/", "").Replace("t.me/", "").TrimStart('@').TrimEnd('/'))
        .Where(x => Regex.IsMatch(x, @"^[a-zA-Z][a-zA-Z0-9_]{3,31}$", RegexOptions.None, RegexTimeout))
        .Distinct(StringComparer.OrdinalIgnoreCase).Take(500).ToList();

    public sealed record Extraction(List<string> Links, int Posts, int DatedPosts, DateTimeOffset? Newest)
    {
        public string Summary => Posts == 0 ? "صفحهٔ پیام‌های عمومی دریافت نشد"
            : DatedPosts == 0 ? "تاریخ پیام‌ها قابل خواندن نیست"
            : Links.Count == 0 ? $"{Posts} پیام؛ بدون لینک مستقیم V2Ray"
            : $"{Links.Count} کاندید از آخرین پیام‌های لینک‌دار · تاریخ {Newest:yyyy-MM-dd}";
    }

    public static Extraction Inspect(string html)
    {
        var links = new List<string>();
        var posts = Regex.Split(html, """<div\b[^>]*\bclass\s*=\s*["'][^"']*\btgme_widget_message_wrap\b[^"']*["'][^>]*>""", RegexOptions.IgnoreCase, RegexTimeout).Skip(1).ToList();
        var dated = new List<(DateTimeOffset Date, string Post)>();
        foreach (var post in posts)
        {
            var date = Regex.Match(post, """\bdatetime\s*=\s*["']([^"']+)["']""", RegexOptions.IgnoreCase, RegexTimeout);
            if (DateTimeOffset.TryParse(date.Groups[1].Value, CultureInfo.InvariantCulture, DateTimeStyles.None, out var timestamp))
                dated.Add((timestamp, post));
        }
        DateTimeOffset? newest = null;
        foreach (var (date, post) in dated.OrderByDescending(x => x.Date))
        {
            var text = Regex.Replace(Regex.Replace(post, @"</?(?:div|p|pre|li|code|time)\b[^>]*>|<br\s*/?>", "\n", RegexOptions.IgnoreCase, RegexTimeout), "<[^>]+>", "", RegexOptions.None, RegexTimeout);
            var hrefs = Regex.Matches(post, """\bhref\s*=\s*["']([^"']+)["']""", RegexOptions.IgnoreCase, RegexTimeout).Select(x => x.Groups[1].Value);
            var decoded = WebUtility.HtmlDecode(string.Join("\n", hrefs) + "\n" + text);
            foreach (Match match in Links.Matches(decoded))
            {
                var link = match.Value;
                if (FmtHandler.ResolveConfig(link, out _) is null || links.Contains(link)) continue;
                links.Add(link);
                newest ??= date;
                if (links.Count == 4) return new(links, posts.Count, dated.Count, newest);
            }
        }
        return new(links, posts.Count, dated.Count, newest);
    }

    public static List<string> ExtractLinks(string html) => Inspect(html).Links;

    public static async Task EnsureSubscriptionAsync()
    {
        var item = await AppManager.Instance.GetSubItem(PoolId) ?? new SubItem { Id = PoolId };
        item.Remarks = PoolName; item.Url = ""; item.Enabled = true; item.AutoUpdateInterval = 0;
        if (await ConfigHandler.AddSubItem(AppManager.Instance.Config, item) != 0)
            throw new IOException("ساخت اشتراک سرور های استخر ناموفق بود.");
    }

    public static bool AcceptSamples(IReadOnlyList<int> samples) =>
        samples.Count == 3 && samples.All(x => x > 0 && x <= 900);

    private static HttpClient Client(IWebProxy? proxy) => new(new SocketsHttpHandler
    {
        Proxy = proxy, UseProxy = proxy != null, ConnectTimeout = TimeSpan.FromSeconds(5),
        AutomaticDecompression = DecompressionMethods.All
    }) { Timeout = TimeSpan.FromSeconds(15), MaxResponseContentBufferSize = 2 * 1024 * 1024 };

    public async Task<int> RunAsync(Func<ProfileItem, Task> connect, IProgress<PoolProgress> progress, CancellationToken token)
    {
        if (!await Gate.WaitAsync(0, token)) throw new InvalidOperationException("جمع‌آوری دیگری در حال اجراست.");
        var config = AppManager.Instance.Config;
        try
        {
            await EnsureSubscriptionAsync();
            progress.Report(new("استخر", $"اشتراک مستقل «{PoolName}» آماده است."));
            progress.Report(new("ساب پیش‌فرض", "بروزرسانی و آزمون ساب پیش‌فرض…"));
            await DicodePingBootstrap.EnsureDefaultsAsync(config);
            var primary = (await AppManager.Instance.SubItems())!.First(x => x.Url == DicodePingBootstrap.DefaultSubscriptionUrl);
            await SubscriptionHandler.UpdateProcess(config, primary.Id, false, (_, _) => Task.CompletedTask);
            token.ThrowIfCancellationRequested();
            var initial = await ProbeAsync(await AppManager.Instance.ProfileItems(primary.Id) ?? [], false, progress, token);
            var best = initial.OrderBy(x => x.Delay).FirstOrDefault();
            if (best.Profile == null) throw new InvalidOperationException("ساب پیش‌فرض مسیر سالمی ندارد؛ دوباره تلاش کنید.");
            progress.Report(new("اتصال", $"شروع اتصال به بهترین مسیر ساب · {best.Delay} ms"));
            await connect(best.Profile);
            token.ThrowIfCancellationRequested();
            progress.Report(new("اتصال", "درگاه محلی آماده است؛ اکنون دریافت کانال‌ها بررسی می‌شود."));
            var proxy = new WebProxy($"socks5://{Global.Loopback}:{AppManager.Instance.GetLocalPort(EInboundProtocol.socks)}");
            var inbound = config.Inbound.FirstOrDefault();
            if (!string.IsNullOrEmpty(inbound?.User)) proxy.Credentials = new NetworkCredential(inbound.User, inbound.Pass);
            using var client = Client(proxy);
            client.DefaultRequestHeaders.UserAgent.ParseAdd("DicodePing/3.9.0");
            client.DefaultRequestHeaders.Accept.ParseAdd("application/vnd.github.raw+json");
            var channels = await PoolNetwork.LoadChannelsAsync((url, ct) => client.GetStringAsync(url, ct), progress, token);
            var collected = new ConcurrentDictionary<string, byte>();
            int completed = 0, failed = 0;
            await Parallel.ForEachAsync(channels, new ParallelOptions { MaxDegreeOfParallelism = 8, CancellationToken = token }, async (channel, ct) =>
            {
                try
                {
                    var html = await client.GetStringAsync($"https://t.me/s/{channel}", ct);
                    var extraction = Inspect(html);
                    if (extraction.Posts == 0 || extraction.DatedPosts == 0) Interlocked.Increment(ref failed);
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
            progress.Report(new("آزمون", $"آغاز سه آزمون مستقل برای {profiles.Count} کانفیگ"));
            var accepted = await ProbeAsync(profiles, true, progress, token);
            token.ThrowIfCancellationRequested();
            if (accepted.Count == 0) throw new InvalidOperationException("کانفیگ واجد شرایط پیدا نشد؛ استخر قبلی حفظ شد.");
            progress.Report(new("ذخیره", $"ذخیرهٔ {accepted.Count} کانفیگ تأییدشده…"));
            await ProfileOperationCoordinator.Gate.WaitAsync(token);
            try
            {
                await EnsureSubscriptionAsync();
                await SQLiteHelper.Instance.ReplaceServerPoolAsync(PoolId, accepted.OrderBy(x => x.Delay).Select(x => x.Profile).ToList(), config.IndexId);
                foreach (var item in accepted) ProfileExManager.Instance.SetTestDelay(item.Profile.IndexId, item.Delay);
                await ProfileExManager.Instance.SaveTo();
            }
            finally { ProfileOperationCoordinator.Gate.Release(); }
            progress.Report(new("پایان", $"{accepted.Count} کانفیگ سالم در استخر ذخیره شد.", accepted.Count, accepted.Count, accepted.Count));
            return accepted.Count;
        }
        finally { Gate.Release(); }
    }

    private static async Task<List<(ProfileItem Profile, int Delay)>> ProbeAsync(List<ProfileItem> profiles, bool strict,
        IProgress<PoolProgress> progress, CancellationToken token)
    {
        var result = new ConcurrentBag<(ProfileItem, int)>();
        var done = 0;
        await PoolBatchRunner.RunAsync(profiles, 12, async chunk =>
        {
            token.ThrowIfCancellationRequested();
            var baseIndex = done;
            var batch = chunk.Select((p, i) => new ServerTestItem { IndexId = p.IndexId, Address = p.Address,
                Port = p.Port, ConfigType = p.ConfigType, Profile = p, QueueNum = i,
                CoreType = AppManager.Instance.GetCoreType(p, p.ConfigType) }).ToList();
            var core = await CoreManager.Instance.LoadCoreConfigSpeedtest(batch);
            if (core == null) {
                progress.Report(new("آزمون", "هستهٔ این دسته آماده نشد؛ جداسازی کانفیگ ناسازگار…"));
                return false;
            }
            try
            {
                await Task.Delay(800, token);
                if (core.HasExited) return false;
                await Parallel.ForEachAsync(batch, new ParallelOptions { MaxDegreeOfParallelism = 6, CancellationToken = token }, async (item, ct) =>
                {
                    var samples = new List<int>();
                    if (item.AllowTest)
                    {
                        var ready = true;
                        try { await PoolNetwork.WaitForListenerAsync(() => item.Port, ct, 10); }
                        catch (IOException) { ready = false; progress.Report(new("آزمون", $"سرور {baseIndex + item.QueueNum + 1} · درگاه هستهٔ آزمون آماده نشد")); }
                        using var client = Client(new WebProxy($"socks5://{Global.Loopback}:{item.Port}"));
                        for (var round = 0; round < (strict ? 3 : 1); round++)
                        {
                            ct.ThrowIfCancellationRequested();
                            using var deadline = CancellationTokenSource.CreateLinkedTokenSource(ct);
                            deadline.CancelAfter(TimeSpan.FromSeconds(strict ? 4 : 8));
                            if (!ready) { samples.Add(-1); continue; }
                            try
                            {
                                var watch = Stopwatch.StartNew();
                                using var response = await client.GetAsync(AppManager.Instance.Config.SpeedTestItem.SpeedPingTestUrl, deadline.Token);
                                samples.Add(response.IsSuccessStatusCode ? Math.Max(1, (int)watch.ElapsedMilliseconds) : -1);
                            }
                            catch (OperationCanceledException) when (ct.IsCancellationRequested) { throw; }
                            catch (Exception) { samples.Add(-1); }
                            progress.Report(new(strict ? "آزمون" : "ساب پیش‌فرض", $"سرور {baseIndex + item.QueueNum + 1} · نوبت {round + 1}/{(strict ? 3 : 1)}: {(samples[^1] > 0 ? $"{samples[^1]} ms" : "ناموفق")}"));
                        }
                        progress.Report(new(strict ? "آزمون" : "ساب پیش‌فرض", $"سرور {item.QueueNum + baseIndex + 1} · پاسخ‌ها: {string.Join(" / ", samples.Select(x => x > 0 ? $"{x} ms" : "ناموفق"))} · {(strict ? (AcceptSamples(samples) ? "پذیرفته" : "رد شد") : "آزمون اولیه")}"));
                        if (strict ? AcceptSamples(samples) : samples[0] > 0)
                            result.Add((item.Profile, samples.Order().ElementAt(samples.Count / 2)));
                    }
                    var completed = Interlocked.Increment(ref done);
                    progress.Report(new(strict ? "آزمون" : "ساب پیش‌فرض", "آزمون واقعی مسیر", completed, profiles.Count, result.Count, Math.Max(0, completed - result.Count)));
                });
            }
            finally { await core.StopAsync(); core.Dispose(); }
            return true;
        }, _ => {
            var completed = Interlocked.Increment(ref done);
            progress.Report(new("آزمون", "کانفیگ ناسازگار با هسته رد شد؛ سایر سرورها بررسی می‌شوند.", completed, profiles.Count, result.Count, Math.Max(0, completed - result.Count)));
        }, token);
        return result.ToList();
    }
}
