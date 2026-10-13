using System.Text.Json;
using ServiceLib.Common;
using ServiceLib.Enums;
using ServiceLib.Handler;
using ServiceLib.Handler.Builder;
using ServiceLib.Handler.SysProxy;
using ServiceLib.Helper;
using ServiceLib.Manager;
using ServiceLib.Models.Configs;
using ServiceLib.Models.Entities;
using ServiceLib.Services;

CliText.Configure(ref args);

if (args.Length == 0 || args.Contains("--help") || args[0] == "help")
{
    Console.WriteLine(CliText.T("""
        دیکد پینگ CLI 4.7.0
        fox accounts|locations       نمایش حساب‌ها یا کشورها
        fox login                    ورود مرحله‌ای، تأیید و انتخاب کشور
        fox verify <account-id>      واردکردن کد تأیید موزیلا
        fox refresh <account-id>     تازه‌سازی سهمیه و ساب حساب
        fox location <id> <REC|CC>   انتخاب کشور یا موقعیت پیشنهادی
        fox remove <account-id>      حذف حساب و ساب از برنامه
        profiles                     نمایش سرورها و تأخیر واقعی (JSON)
        import <file>                واردکردن لینک‌ها یا فایل JSON
        refresh                      تازه‌سازی اشتراک‌های فعال
        ping                         آزمون تأخیر واقعی و مرتب‌سازی
        connect [id | --best]         اتصال تا فشردن Ctrl+C
        check <file> --engine xray|sing-box|mihomo
        run <file> --engine xray|sing-box|mihomo
        scan-cf <file>                تست HTTPS آدرس‌های کلودفلر
        --data <directory>           مسیر مستقل ذخیره داده‌ها
        --tun                        تونل کل سیستم؛ نیازمند دسترسی مدیر
        --system-proxy               تنظیم پروکسی سیستم در این اجرا
        --lang fa|en                 زبان راهنما و پیام‌ها
        """, """
        DicodePing CLI 4.7.0
        fox accounts|locations       List Fox accounts or provider locations
        fox login                    Sign in (email/password read privately from stdin)
        fox verify <account-id>      Enter Mozilla verification code
        fox refresh <account-id>     Update allowance and the managed profile
        fox location <id> <REC|CC>   Select a country or recommended location
        fox remove <account-id>      Remove local account and subscription
        profiles                     List profile IDs, real latency and locations (JSON)
        import <file>                Import share links or native JSON configurations
        refresh                      Update enabled subscriptions
        ping                         Test real latency and sort successful profiles first
        connect [id | --best]         Run a profile until Ctrl+C; uses saved successful tests
        check <file> --engine xray|sing-box|mihomo
        run <file> --engine xray|sing-box|mihomo
        scan-cf <file>                Test supplied Cloudflare IPs with verified HTTPS
        --data <directory>           Separate writable data directory
        --tun                        Enable full-system TUN (requires administrator access)
        --system-proxy               Also set system proxy for this foreground session
        --lang fa|en                 Help and message language
        """));
    return 0;
}
if (args[0] is "--version" or "version") { Console.WriteLine("4.7.0"); return 0; }
string? Option(string name) { var i = Array.IndexOf(args, name); return i >= 0 && i+1 < args.Length ? args[i+1] : null; }
var data = Path.GetFullPath(Option("--data") ?? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "DicodePing-CLI"));
Directory.CreateDirectory(data);
Environment.SetEnvironmentVariable("DICODE_DATA_DIR", data);
using var cancellation = new CancellationTokenSource();
Console.CancelKeyPress += (_, e) => { e.Cancel = true; cancellation.Cancel(); };
try
{
    using var instance = new FileStream(Path.Combine(data, "cli.lock"), FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.None);
    if (args[0] is "run" or "check") return await NativeCommands.Execute(args, Option("--engine") ?? "xray", cancellation.Token);
    if (args[0] == "scan-cf") return await NativeCommands.Scan(args, cancellation.Token);
    if (!AppManager.Instance.InitApp()) throw new InvalidOperationException(CliText.T("پیکربندی برنامه آماده نشد", "Could not initialize configuration"));
    var config = AppManager.Instance.Config;
    ServiceLib.Resx.ResUI.Culture = new System.Globalization.CultureInfo(CliText.Persian ? "fa-IR" : "en-US");
    System.Globalization.CultureInfo.CurrentUICulture = ServiceLib.Resx.ResUI.Culture;
    await ConfigHandler.InitBuiltinDNS(config);
    await ConfigHandler.InitBuiltinFullConfigTemplate(config);
    await ProfileExManager.Instance.Init();
    await BundledRuntimeInstaller.InstallAsync(Path.Combine(AppContext.BaseDirectory, "bin"), Utils.GetBinPath(""), "4.7.0");
    Task Output(bool success, string text) { Console.Error.WriteLine(text); return Task.CompletedTask; }
    await CoreManager.Instance.Init(config, Output);
    switch (args[0])
    {
        case "fox":
            return await FoxCommands.Execute(args, cancellation.Token);
        case "profiles":
            var extra = (await ProfileExManager.Instance.GetProfileExs()).ToDictionary(x => x.IndexId);
            Console.WriteLine(JsonSerializer.Serialize((await AppManager.Instance.ProfileModels("", "")).Select(p => new {
                id = p.IndexId, name = p.Remarks, type = p.ConfigType.ToString(),
                latency = extra.GetValueOrDefault(p.IndexId)?.Delay, location = extra.GetValueOrDefault(p.IndexId)?.IpInfo
            }), new JsonSerializerOptions { WriteIndented = true }));
            break;
        case "import":
            if (args.Length < 2) throw new ArgumentException(CliText.T("فرمان import به مسیر فایل نیاز دارد", "import requires a file"));
            var imported = await ConfigHandler.AddBatchServers(config, await File.ReadAllTextAsync(args[1], cancellation.Token), "", false);
            if (imported <= 0) throw new InvalidDataException(CliText.T("سرور معتبری در فایل وجود ندارد", "No valid profiles in file"));
            Console.WriteLine(CliText.T($"{imported} سرور وارد شد", $"Imported {imported} profiles"));
            break;
        case "refresh":
            await SubscriptionHandler.UpdateProcess(config, "", false, Output, cancellation.Token);
            break;
        case "ping":
            return await Ping(config, cancellation.Token);
        case "connect":
            var profiles = await AppManager.Instance.ProfileModels("", "");
            var selectedId = args.Length > 1 && !args[1].StartsWith("--") ? args[1] : config.IndexId;
            if (args.Contains("--best"))
            {
                var results = await ProfileExManager.Instance.GetProfileExs();
                var best = results.Where(x => x.Delay > 0 && profiles.Any(p => p.IndexId == x.IndexId)).OrderBy(x => x.Delay).FirstOrDefault();
                if (best is null) { await Ping(config, cancellation.Token); best = (await ProfileExManager.Instance.GetProfileExs()).Where(x => x.Delay > 0 && profiles.Any(p => p.IndexId == x.IndexId)).OrderBy(x => x.Delay).FirstOrDefault(); }
                selectedId = best?.IndexId ?? throw new InvalidOperationException(CliText.T("هیچ سروری از آزمون تأخیر واقعی عبور نکرد", "No server passed the real latency test"));
            }
            var node = await AppManager.Instance.GetProfileItem(selectedId) ?? throw new InvalidOperationException(CliText.T("شناسه سرور یا --best را انتخاب کنید", "Select a profile ID or --best"));
            if (args.Contains("--tun") && !Utils.IsAdministrator()) throw new InvalidOperationException(CliText.T("برای --tun برنامه را با دسترسی مدیر اجرا کنید", "Run the CLI as administrator/root for --tun"));
            config.TunModeItem.EnableTun = args.Contains("--tun");
            config.SystemProxyItem.SysProxyType = args.Contains("--system-proxy") ? ESysProxyType.ForcedChange : ESysProxyType.ForcedClear;
            var contexts = await CoreConfigContextBuilder.BuildAll(config, node);
            if (!contexts.Success) throw new InvalidOperationException(CliText.T("اعتبارسنجی سرور ناموفق بود", "Profile validation failed"));
            await CoreManager.Instance.LoadCore(contexts.MainResult.Context, contexts.PreSocksResult?.Context);
            if (!CoreManager.Instance.IsRunning) throw new InvalidOperationException(CliText.T("هسته اجرا نشد", "Core did not start"));
            if (args.Contains("--system-proxy")) await SysProxyHandler.UpdateSysProxy(config, false);
            Console.Error.WriteLine(CliText.T($"{node.Remarks} فعال است. برای توقف Ctrl+C را بزنید.", $"Running {node.Remarks}. Press Ctrl+C to stop."));
            while (!cancellation.IsCancellationRequested && CoreManager.Instance.IsRunning) await Task.Delay(500, cancellation.Token);
            if (!cancellation.IsCancellationRequested) throw new IOException(CliText.T("هسته به‌صورت غیرمنتظره متوقف شد", "Core stopped unexpectedly"));
            break;
        default: throw new ArgumentException(CliText.T("فرمان ناشناخته است؛ از --help استفاده کنید", "Unknown command; use --help"));
    }
    return 0;
}
catch (OperationCanceledException) when (cancellation.IsCancellationRequested) { return 130; }
catch (Exception error) { Console.Error.WriteLine(args.Contains("--verbose") ? error.ToString() : CliText.Error(error)); return 1; }
finally
{
    await CoreManager.Instance.CoreStop();
    if (AppManager.Instance.Config is { } config && args.Contains("--system-proxy")) await SysProxyHandler.UpdateSysProxy(config, true);
}

static async Task<int> Ping(Config config, CancellationToken token)
{
    var profiles = new List<ProfileItem>();
    foreach (var model in await AppManager.Instance.ProfileModels("", ""))
        if (await AppManager.Instance.GetProfileItem(model.IndexId) is { } node) profiles.Add(node);
    var completed = new HashSet<string>();
    var service = new SpeedtestService(config, result => {
        lock (completed)
            if (!string.IsNullOrEmpty(result.IndexId) && int.TryParse(result.Delay, out var delay) && completed.Add(result.IndexId))
                Console.WriteLine(JsonSerializer.Serialize(new { id = result.IndexId, latency = delay, completed = completed.Count, total = profiles.Count }));
        if (result.Delay?.Length > 0 && !int.TryParse(result.Delay, out _)) Console.Error.WriteLine(result.Delay);
        if (result.Speed?.Length > 0) Console.Error.WriteLine(result.Speed);
        return Task.CompletedTask;
    });
    await service.RunLoop(ESpeedActionType.Realping, profiles, token);
    token.ThrowIfCancellationRequested();
    await ConfigHandler.SortServers(config, "", nameof(EServerColName.DelayVal), true);
    await ProfileExManager.Instance.SaveTo();
    var ids = profiles.Select(p => p.IndexId).ToHashSet();
    return (await ProfileExManager.Instance.GetProfileExs()).Any(p => ids.Contains(p.IndexId) && p.Delay > 0) ? 0 : 2;
}
