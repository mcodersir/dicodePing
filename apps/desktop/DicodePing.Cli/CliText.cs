using System.Globalization;
using ServiceLib.Services;

internal static class CliText
{
    public static bool Persian { get; private set; }
    public static void Configure(ref string[] args)
    {
        var i = Array.IndexOf(args, "--lang");
        var language = i >= 0 && i + 1 < args.Length ? args[i + 1] : "en";
        Persian = language.StartsWith("fa", StringComparison.OrdinalIgnoreCase);
        var culture = new CultureInfo(Persian ? "fa-IR" : "en-US");
        CultureInfo.CurrentUICulture = CultureInfo.DefaultThreadCurrentUICulture = culture;
        ServiceLib.Resx.ResUI.Culture = culture;
        if (i >= 0) args = args.Where((_, index) => index != i && index != i + 1).ToArray();
        Console.OutputEncoding = System.Text.Encoding.UTF8;
    }
    public static string T(string fa, string en) => Persian ? fa : en;
    public static string Error(Exception e) => e is FoxException f ? f.Code switch {
        "credentials" => T("ایمیل یا رمز عبور درست نیست.", "Incorrect email or password."),
        "login_required" => T("نشست حساب منقضی یا رد شده است؛ دوباره وارد شوید.", "Account session expired or was rejected. Sign in again."),
        "activation_required" => T("فعال‌سازی Firefox VPN رد شد؛ دوباره تلاش کنید.", "Firefox VPN activation was rejected. Retry."),
        "quota_exceeded" => T("سهمیه یا سقف درخواست تمام شده است.", "Account quota or request limit reached."),
        "verification_required" => T("تأیید حساب موزیلا را کامل کنید و دوباره تلاش کنید.", "Complete Mozilla account verification and retry."),
        "network" => T("ارتباط با سرویس برقرار نشد؛ اتصال اینترنت را بررسی کنید.", "Could not reach the provider. Check your connection."),
        "missing_helper" => T("هسته روباه پیدا نشد؛ بسته کامل را نصب کنید.", "Fox helper missing. Install the complete package."),
        _ => T("عملیات روباه ناموفق بود؛ اطلاعات ورودی و اتصال را بررسی کنید.", f.Message)
    } : e.Message;
}
