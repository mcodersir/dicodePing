using System.Text.Json.Nodes;
using ServiceLib.Services;
using Avalonia.Layout;
using Avalonia.Input.Platform;

namespace v2rayN.Desktop.Views;

public static class FoxUi
{
    public const string Icon = "M4,3 L8,7 L12,5 L16,7 L20,3 L22,13 L17,19 L12,22 L7,19 L2,13 Z M8,12 L10,14 M16,12 L14,14 M10,18 L14,18";
    public static string T(string fa, string en) => (ResUI.Culture ?? System.Globalization.CultureInfo.CurrentUICulture).TwoLetterISOLanguageName == "fa" ? fa : en;
    public static string Error(Exception e) => e is FoxException f ? f.Code switch {
        "account_not_found" => T("حساب Mozilla با این ایمیل پیدا نشد؛ ابتدا در سایت موزیلا حساب بسازید.", "No Mozilla account exists for this email. Create one on Mozilla’s website first."),
        "credentials" => T("ایمیل یا رمز عبور درست نیست.", "Incorrect email or password."),
        "login_required" => T("نشست حساب موزیلا منقضی یا رد شده است؛ دوباره وارد شوید.", "Your Mozilla session expired or was rejected. Sign in again."),
        "activation_required" => T("فعال‌سازی Firefox VPN رد شد؛ دوباره تلاش کنید یا وارد حساب شوید.", "Firefox VPN activation was rejected. Retry or sign in again."),
        "network" => T("ارتباط با سرویس برقرار نشد؛ اتصال اینترنت را بررسی کنید.", "Could not reach the provider. Check your connection."),
        "input" => T("اطلاعات واردشده معتبر نیست؛ ایمیل و کد تأیید را بررسی کنید.", "Invalid input. Check your email and verification code."),
        "missing_helper" => T("هسته روباه پیدا نشد؛ بسته کامل برنامه را نصب کنید.", "Fox helper is missing. Install the complete package."),
        "quota_exceeded" => T("سهمیه یا سقف درخواست حساب تمام شده؛ زمان بازنشانی را بررسی کنید.", "Account allowance or request limit reached. Check its reset date."),
        "verification_required" => T("حساب به تأیید در سایت Mozilla نیاز دارد. تأیید را کامل کنید و دوباره تلاش کنید.", "Complete Mozilla's interactive account verification, then retry."),
        "port_in_use" => T("پورت 7854 در اختیار پروکسی دیگری است؛ آن را ببندید یا کانفیگ SOCKS آن را انتخاب کنید.", "Port 7854 is occupied by another proxy. Stop it or use its SOCKS profile."),
        "unreachable" => T("هیچ مسیر روباه از آزمون واقعی عبور نکرد؛ اتصال مستقیم جایگزین نمی‌شود.", "No Firefox route passed the real traffic test; there is no direct fallback."),
        _ => T("عملیات روباه ناموفق بود؛ اطلاعات ورودی و اتصال را بررسی کنید.", f.Message)
    } : e.Message;
    public static string CountryLabel(string? value)
    {
        var code = value?.Trim().ToUpperInvariant();
        if (string.IsNullOrEmpty(code)) return string.Empty; // Avalonia recycles containers with null content.
        if (code == "REC") return T("پیشنهادی · مسیر خودکار Mozilla", "Recommended · Mozilla anycast route");
        try { return new System.Globalization.RegionInfo(code).DisplayName + " · " + code; }
        catch (ArgumentException) { return code; }
    }
    public static Avalonia.Controls.Templates.FuncDataTemplate<string> CountryTemplate() =>
        new((value, _) => new TextBlock { Text = CountryLabel(value) });
    public static string Quota(FoxAccount account)
    {
        var maximum = account.Info["quota_max"]?.GetValue<long>(); var remaining = account.Info["quota_remaining"]?.GetValue<long>();
        var text = maximum is null || remaining is null ? T("سهمیه هنوز توسط سرویس گزارش نشده است.", "The provider has not reported an allowance yet.")
            : T($"مصرف‌شده: {Math.Max(0, maximum.Value - remaining.Value) / 1e9:0.##} GB · باقی‌مانده: {remaining / 1e9:0.##} از {maximum / 1e9:0.##} GB", $"Used: {Math.Max(0, maximum.Value - remaining.Value) / 1e9:0.##} GB · Remaining: {remaining / 1e9:0.##} of {maximum / 1e9:0.##} GB");
        if (account.Info["quota_reset"]?.GetValue<long>() is > 0 and <= 253402300799L and var reset) text += " · " + T("بازنشانی: ", "Reset: ") + DateTimeOffset.FromUnixTimeSeconds(reset).ToLocalTime().ToString("yyyy-MM-dd");
        return text;
    }
}
public sealed class FoxWindow : Window
{
    public FoxWindow(MainWindowViewModel main)
    {
        Title = FoxUi.T("روباه · DicodePing", "Fox · DicodePing"); Width = 580; Height = 700; MinWidth = 320; MinHeight = 360;
        WindowStartupLocation = WindowStartupLocation.CenterOwner;
        FlowDirection = FoxUi.T("fa", "en") == "fa" ? FlowDirection.RightToLeft : FlowDirection.LeftToRight;
        var accounts = new ComboBox { HorizontalAlignment = HorizontalAlignment.Stretch };
        var email = new TextBox { PlaceholderText = FoxUi.T("ایمیل حساب Mozilla", "Mozilla account email"), FlowDirection = FlowDirection.LeftToRight };
        var password = new TextBox { PlaceholderText = FoxUi.T("رمز عبور · ذخیره نمی‌شود", "Password · never saved"), PasswordChar = '●' };
        var code = new TextBox { PlaceholderText = FoxUi.T("کد تأیید حساب", "Account verification code"), FlowDirection = FlowDirection.LeftToRight, IsVisible = false };
        var status = new TextBlock { TextWrapping = TextWrapping.Wrap }; var quota = new TextBlock { TextWrapping = TextWrapping.Wrap };
        var country = new ComboBox { HorizontalAlignment = HorizontalAlignment.Stretch, ItemsSource = new[] { "REC" }, SelectedIndex = 0 };
        country.Name = "FoxCountrySelector"; country.ItemTemplate = FoxUi.CountryTemplate();
        var login = new Button { Content = FoxUi.T("ورود و افزودن حساب", "Sign in and add account"), HorizontalAlignment = HorizontalAlignment.Stretch };
        var verify = new Button { Content = FoxUi.T("تأیید کد", "Verify code"), IsVisible = false };
        var refresh = new Button { Content = FoxUi.T("بررسی حساب و افزودن/تازه‌سازی ساب", "Check account and sync subscription") };
        var connect = new Button { Content = FoxUi.T("اتصال به روباه", "Connect to Fox"), HorizontalAlignment = HorizontalAlignment.Stretch };
        var copyProxy = new Button { Content = FoxUi.T("کپی لینک SOCKS روباه · 127.0.0.1:7854", "Copy Fox SOCKS link · 127.0.0.1:7854"), HorizontalAlignment = HorizontalAlignment.Stretch };
        var remove = new Button { Content = FoxUi.T("حذف حساب و ساب از برنامه", "Remove local account and subscription") };
        foreach (var button in new[] { login, verify, refresh, connect, copyProxy, remove }) { button.Content = new TextBlock { Text = button.Content?.ToString(), TextWrapping = TextWrapping.Wrap }; button.HorizontalAlignment = HorizontalAlignment.Stretch; }
        connect.MinHeight = 68; connect.CornerRadius = new CornerRadius(20);
        connect.HorizontalContentAlignment = HorizontalAlignment.Center;
        connect.Classes.Add("accent");
        connect.Content = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 12, HorizontalAlignment = HorizontalAlignment.Center, Children = {
            new Avalonia.Controls.Shapes.Path { Data = Geometry.Parse(FoxUi.Icon), Width = 28, Height = 28, Stretch = Stretch.Uniform, Stroke = Avalonia.Media.Brushes.White, StrokeThickness = 1.8 },
            new TextBlock { Text = FoxUi.T("اتصال به روباه", "Connect to Fox"), FontSize = 21, FontWeight = FontWeight.SemiBold, VerticalAlignment = VerticalAlignment.Center }
        } };
        var steps = new TextBlock { TextWrapping = TextWrapping.Wrap, FontSize = 14, FontWeight = FontWeight.SemiBold };
        var openAccount = new Button { Content = FoxUi.T("۱ · باز کردن سایت Mozilla و ساخت حساب", "1 · Open Mozilla and create an account"), HorizontalAlignment = HorizontalAlignment.Stretch };
        openAccount.Click += (_, _) => ProcUtils.ProcessStart("https://accounts.firefox.com/signup");
        var browserLogin = new Button { Content = FoxUi.T("ورود امن با مرورگر موزیلا", "Sign in on Mozilla’s page"), MinHeight = 60, HorizontalAlignment = HorizontalAlignment.Stretch };
        var credentialsPanel = new StackPanel { Spacing = 12, Children = {
            new TextBlock { Text = FoxUi.T("با ایمیل و رمز حساب Firefox در صفحهٔ رسمی موزیلا وارد شوید. کدهای تأیید را همان‌جا وارد کنید؛ Google و Apple پشتیبانی نمی‌شوند.", "Use your Firefox email and password on Mozilla’s official page. Complete verification there; Google and Apple are not supported."), TextWrapping = TextWrapping.Wrap }, browserLogin } };
        var verificationPanel = new StackPanel { Spacing = 12, Children = { new TextBlock { Text = FoxUi.T("ورود قبلی را در صفحهٔ رسمی موزیلا کامل کنید.", "Complete sign-in on Mozilla’s official page."), TextWrapping = TextWrapping.Wrap } } };
        var connectionPanel = new StackPanel { Spacing = 12, Children = {
            quota, new TextBlock { Text = FoxUi.T("پس از ورود، سرور روباه در فهرست پروفایل‌ها هم قابل اتصال است.", "After sign-in, connect from the profile list or this page."), TextWrapping = TextWrapping.Wrap }, new TextBlock { Text = FoxUi.T("کشور سرور", "Server country") }, country, copyProxy, refresh, remove } };
        var add = new Button { Content = FoxUi.T("افزودن حساب دیگر", "Add another account") };
        var back = new Button { Content = FoxUi.T("بازگشت به حساب‌ها", "Back to accounts") };
        var adding = false; bool busy = false;
        void Render() {
            var account = accounts.SelectedItem as FoxAccount;
            var pending = !adding && account?.Pending == true;
            var ready = !adding && account is not null && !account.Pending;
            credentialsPanel.IsVisible = adding || account is null || pending;
            browserLogin.IsEnabled = !busy;
            verificationPanel.IsVisible = pending;
            connectionPanel.IsVisible = ready;
            add.IsVisible = !adding && account is not null;
            back.IsVisible = adding && accounts.ItemCount > 0;
            steps.Text = credentialsPanel.IsVisible ? FoxUi.T("۱ · ورود به حساب", "1 · Sign in")
                : pending ? FoxUi.T("۲ · تأیید حساب", "2 · Verify account") : FoxUi.T("۳ · انتخاب کشور و اتصال", "3 · Choose country and connect");
            login.IsEnabled = !busy && !string.IsNullOrWhiteSpace(email.Text) && !string.IsNullOrEmpty(password.Text);
            verify.IsEnabled = !busy && !string.IsNullOrWhiteSpace(code.Text);
            connect.IsVisible = ready;
            connect.IsEnabled = refresh.IsEnabled = !busy && ready;
            remove.IsEnabled = !busy && account is not null;
            accounts.IsEnabled = country.IsEnabled = email.IsEnabled = password.IsEnabled = code.IsEnabled = add.IsEnabled = back.IsEnabled = !busy;
        }
        var cts = new CancellationTokenSource(); Closed += (_, _) => cts.Cancel();
        async Task Load(string? id = null) {
            var saved = await FoxAccounts.ListAsync(); accounts.ItemsSource = saved; accounts.SelectedItem = saved.FirstOrDefault(a => a.Id == id) ?? saved.FirstOrDefault();
        }
        void Selection() { if (accounts.SelectedItem is FoxAccount account) { quota.Text = FoxUi.Quota(account); verify.IsVisible = code.IsVisible = account.Pending; country.SelectedItem = account.Country; } Render(); }
        accounts.SelectionChanged += (_, _) => { adding = false; Selection(); };
        add.Click += (_, _) => { adding = true; email.Text = ""; code.Text = ""; status.Text = ""; Render(); email.Focus(); };
        back.Click += (_, _) => { adding = false; password.Text = ""; Render(); };
        email.TextChanged += (_, _) => Render(); password.TextChanged += (_, _) => Render(); code.TextChanged += (_, _) => Render();
        async Task Run(Func<Task> work) {
            if (busy) return; busy = true; Render();
            status.Text = FoxUi.T("در حال ارتباط امن با سرویس…", "Contacting the provider securely…");
            try { await work(); } catch (OperationCanceledException) { status.Text = FoxUi.T("لغو شد", "Cancelled"); }
            catch (Exception error) { status.Text = FoxUi.Error(error); await Load((accounts.SelectedItem as FoxAccount)?.Id); }
            finally { password.Text = ""; busy = false; Render(); }
        }
        country.SelectionChanged += async (_, _) => {
            if (busy || adding || accounts.SelectedItem is not FoxAccount account || account.Pending
                || country.SelectedItem is not string chosen || chosen == account.Country) return;
            await Run(async () => {
                account.Country = chosen; await FoxAccounts.SaveAsync(account); await FoxProfiles.SyncAsync(account);
                await main.ProfilesViewModel.RefreshSubscriptions(); await main.ProfilesViewModel.RefreshServersBiz();
                status.Text = FoxUi.T("کشور برای اتصال بعدی ذخیره شد؛ از فهرست سرورها هم می‌توانید وصل شوید.", "Location saved for your next connection. You can also connect from the server list.");
            });
        };
        async Task RefreshViews() { await main.ProfilesViewModel.RefreshSubscriptions(); await main.ProfilesViewModel.RefreshServersBiz(); }
        browserLogin.Click += async (_, _) => await Run(async () => {
            var account = await new FoxBrowserWindow().ShowDialog<FoxAccount?>(this);
            if (account is null) return;
            adding = false; await Load(account.Id); await RefreshViews();
            status.Text = FoxUi.T("حساب تأیید شد؛ برای اتصال دکمهٔ بالای صفحه را بزنید.", "Account verified. Use the connect button at the top.");
        });
        refresh.Click += async (_, _) => await Run(async () => {
            if (accounts.SelectedItem is not FoxAccount account) return;
            account.Country = country.SelectedItem?.ToString() ?? "REC"; await FoxAccounts.SaveAsync(account);
            await FoxAccounts.RefreshAsync(account.Id, true, cts.Token); await Load(account.Id); await RefreshViews(); status.Text = FoxUi.T("سهمیه و ساب تازه شدند؛ یک سرور برای این حساب باقی می‌ماند.", "Allowance and subscription refreshed; this account retains one profile.");
        });
        connect.Click += async (_, _) => await Run(async () => {
            var requestVersion = main.ProfilesViewModel.ConnectionRequestVersion;
            if (accounts.SelectedItem is not FoxAccount account || account.Pending) throw new FoxException("login_required", "Complete account sign-in first");
            account.Country = country.SelectedItem?.ToString() ?? "REC"; await FoxAccounts.SaveAsync(account); await FoxProfiles.SyncAsync(account); await RefreshViews();
            var sub = (await AppManager.Instance.SubItems()).First(s => s.Url == "dicode-fox://" + account.Id); var node = (await AppManager.Instance.ProfileItems(sub.Id)).Single();
            await main.ConnectPoolProfileAsync(node.IndexId, cts.Token, requestVersion);
            status.Text = CoreManager.Instance.IsRunning ? FoxUi.T("روباه فعال شد؛ جزئیات و ترافیک در خانه دیده می‌شوند.", "Fox is active; connection details and traffic are shown on Home.") : FoxUi.T("اتصال برقرار نشد؛ گزارش را بررسی کنید.", "Connection did not start; check the log.");
        });
        copyProxy.Click += async (_, _) => await Run(async () => {
            if (Clipboard is { } clipboard) await clipboard.SetTextAsync(FoxProfiles.ShareUri);
            status.Text = FoxUi.T("لینک کپی شد؛ هنگام اتصال روباه، پروکسی محلی فعال است.", "Link copied; the local proxy is active while Fox is connected.");
        });
        remove.Click += async (_, _) => await Run(async () => {
            if (accounts.SelectedItem is not FoxAccount account) return;
            var selected = await AppManager.Instance.GetProfileItem(AppManager.Instance.Config.IndexId);
            if (FoxProfiles.Read(selected)?.AccountId == account.Id && main.ProfilesViewModel.StopConnection is { } stop) await stop();
            await FoxAccounts.RemoveAsync(account.Id); await Load(); await RefreshViews(); status.Text = FoxUi.T("حساب فقط از این برنامه حذف شد.", "Account removed from this application only.");
        });
        Opened += async (_, _) => {
            try {
                await Load(); var locations = await FoxAccounts.RequestAsync(new JsonObject { ["operation"] = "locations" }, cts.Token);
                var values = new[] { "REC" }.Concat((locations["locations"] as JsonArray ?? []).Select(l => l?["country_code"]?.ToString() ?? "").Where(x => x.Length == 2).Distinct()).ToArray();
                country.ItemsSource = values; country.SelectedItem = (accounts.SelectedItem as FoxAccount)?.Country ?? "REC";
            } catch (Exception e) { status.Text = FoxUi.Error(e); }
        };
        Render();
        Content = new ScrollViewer { Content = new StackPanel { Margin = new Thickness(22), Spacing = 13, Children = {
            new Avalonia.Controls.Shapes.Path { Data = Geometry.Parse(FoxUi.Icon), Width = 32, Height = 32, Stretch = Stretch.Uniform, StrokeThickness = 1.8, Stroke = new SolidColorBrush(Color.Parse("#C77739")), HorizontalAlignment = HorizontalAlignment.Left },
            new TextBlock { Text = FoxUi.T("روباه", "Fox"), FontSize = 28, FontWeight = FontWeight.SemiBold },
            connect,
            new TextBlock { Text = FoxUi.T("اتصال غیررسمی Firefox VPN با حساب شما. سهمیه و موقعیت‌های مجاز را Mozilla تعیین می‌کند؛ معمولاً تا ۵۰ گیگابایت در ماه برای حساب واجد شرایط. رمز عبور ذخیره نمی‌شود.", "Unofficial Firefox VPN connection using your account. Mozilla controls eligibility, locations and allowance, usually up to 50 GB/month for eligible accounts. Passwords are never stored."), TextWrapping = TextWrapping.Wrap },
            new TextBlock { Text = FoxUi.T("حساب‌های شما", "Your accounts"), FontWeight = FontWeight.SemiBold }, accounts, add, back, new SponsorBanner { Placement = "fox" }, steps, credentialsPanel, verificationPanel, connectionPanel, status,
            new TextBlock { Text = FoxUi.T("TCP و DNS رمزگذاری‌شده پشتیبانی می‌شوند؛ UDP عمومی پشتیبانی نمی‌شود. حذف ساب آن را خودکار برنمی‌گرداند؛ دکمهٔ تازه‌سازی امکان افزودن دوباره را دارد.", "Supports TCP and encrypted DNS, not arbitrary UDP. Deleted subscriptions stay deleted until you explicitly sync them again."), TextWrapping = TextWrapping.Wrap, Opacity = 0.7 }
        } } };
    }
}
