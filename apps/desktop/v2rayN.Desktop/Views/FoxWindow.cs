using System.Text.Json.Nodes;
using ServiceLib.Services;
using Avalonia.Layout;

namespace v2rayN.Desktop.Views;

public static class FoxUi
{
    public const string Icon = "M4,3 L8,7 L12,5 L16,7 L20,3 L22,13 L17,19 L12,22 L7,19 L2,13 Z M8,12 L10,14 M16,12 L14,14 M10,18 L14,18";
    public static string T(string fa, string en) => ResUI.Culture?.TwoLetterISOLanguageName == "fa" ? fa : en;
    public static string Error(Exception e) => e is FoxException f ? f.Code switch {
        "credentials" => T("ایمیل یا رمز عبور درست نیست.", "Incorrect email or password."),
        "login_required" => T("نشست یا دسترسی حساب توسط Mozilla رد شد؛ دوباره وارد شوید و وضعیت حساب را بررسی کنید.", "Mozilla rejected the account session or access. Sign in and check account eligibility."),
        "quota_exceeded" => T("سهمیه یا سقف درخواست حساب تمام شده؛ زمان بازنشانی را بررسی کنید.", "Account allowance or request limit reached. Check its reset date."),
        "verification_required" => T("حساب به تأیید در سایت Mozilla نیاز دارد. تأیید را کامل کنید و دوباره تلاش کنید.", "Complete Mozilla's interactive account verification, then retry."),
        "unreachable" => T("هیچ مسیر روباه از آزمون واقعی عبور نکرد؛ اتصال مستقیم جایگزین نمی‌شود.", "No Firefox route passed the real traffic test; there is no direct fallback."),
        _ => f.Message
    } : e.Message;
    public static string Quota(FoxAccount account)
    {
        var maximum = account.Info["quota_max"]?.GetValue<long>(); var remaining = account.Info["quota_remaining"]?.GetValue<long>();
        var text = maximum is null || remaining is null ? T("سهمیه هنوز توسط سرویس گزارش نشده است.", "The provider has not reported an allowance yet.")
            : T($"باقی‌مانده: {remaining / 1e9:0.##} از {maximum / 1e9:0.##} GB", $"Remaining: {remaining / 1e9:0.##} of {maximum / 1e9:0.##} GB");
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
        var accounts = new ComboBox { HorizontalAlignment = HorizontalAlignment.Stretch };
        var email = new TextBox { PlaceholderText = FoxUi.T("ایمیل حساب Mozilla", "Mozilla account email"), FlowDirection = FlowDirection.LeftToRight };
        var password = new TextBox { PlaceholderText = FoxUi.T("رمز عبور · ذخیره نمی‌شود", "Password · never saved"), PasswordChar = '●' };
        var code = new TextBox { PlaceholderText = FoxUi.T("کد تأیید حساب", "Account verification code"), FlowDirection = FlowDirection.LeftToRight, IsVisible = false };
        var status = new TextBlock { TextWrapping = TextWrapping.Wrap }; var quota = new TextBlock { TextWrapping = TextWrapping.Wrap };
        var country = new ComboBox { HorizontalAlignment = HorizontalAlignment.Stretch, ItemsSource = new[] { "REC" }, SelectedIndex = 0 };
        var login = new Button { Content = FoxUi.T("ورود و افزودن حساب", "Sign in and add account"), HorizontalAlignment = HorizontalAlignment.Stretch };
        var verify = new Button { Content = FoxUi.T("تأیید کد", "Verify code"), IsVisible = false };
        var refresh = new Button { Content = FoxUi.T("بررسی حساب و افزودن/تازه‌سازی ساب", "Check account and sync subscription") };
        var connect = new Button { Content = FoxUi.T("اتصال به روباه", "Connect to Fox"), HorizontalAlignment = HorizontalAlignment.Stretch };
        var remove = new Button { Content = FoxUi.T("حذف حساب و ساب از برنامه", "Remove local account and subscription") };
        foreach (var button in new[] { login, verify, refresh, connect, remove }) { button.Content = new TextBlock { Text = button.Content?.ToString(), TextWrapping = TextWrapping.Wrap }; button.HorizontalAlignment = HorizontalAlignment.Stretch; }
        var cts = new CancellationTokenSource(); bool busy = false; Closed += (_, _) => cts.Cancel();
        async Task Load(string? id = null) {
            var saved = await FoxAccounts.ListAsync(); accounts.ItemsSource = saved; accounts.SelectedItem = saved.FirstOrDefault(a => a.Id == id) ?? saved.FirstOrDefault();
        }
        void Selection() { if (accounts.SelectedItem is FoxAccount account) { quota.Text = FoxUi.Quota(account); verify.IsVisible = code.IsVisible = account.Pending; country.SelectedItem = account.Country; } }
        accounts.SelectionChanged += (_, _) => Selection();
        async Task Run(Func<Task> work) {
            if (busy) return; busy = true; login.IsEnabled = verify.IsEnabled = refresh.IsEnabled = connect.IsEnabled = remove.IsEnabled = false;
            status.Text = FoxUi.T("در حال ارتباط امن با سرویس…", "Contacting the provider securely…");
            try { await work(); } catch (OperationCanceledException) { status.Text = FoxUi.T("لغو شد", "Cancelled"); }
            catch (Exception error) { status.Text = FoxUi.Error(error); }
            finally { password.Text = ""; busy = false; login.IsEnabled = verify.IsEnabled = refresh.IsEnabled = connect.IsEnabled = remove.IsEnabled = true; }
        }
        async Task RefreshViews() { await main.ProfilesViewModel.RefreshSubscriptions(); await main.ProfilesViewModel.RefreshServersBiz(); }
        login.Click += async (_, _) => await Run(async () => {
            var account = await FoxAccounts.LoginAsync(email.Text ?? "", password.Text ?? "", cts.Token); await Load(account.Id); await RefreshViews();
            status.Text = account.Pending ? FoxUi.T("کد تأیید حساب را وارد کنید؛ هنوز اتصال فعال نشده است.", "Enter the account verification code. The connection is not active yet.") : FoxUi.T("حساب تأیید شد؛ ساب روباه با یک سرور اضافه شد.", "Account verified; Fox subscription with one profile added.");
        });
        verify.Click += async (_, _) => await Run(async () => {
            if (accounts.SelectedItem is not FoxAccount account) return;
            await FoxAccounts.VerifyAsync(account.Id, code.Text ?? "", cts.Token); code.Text = ""; await Load(account.Id); await RefreshViews(); status.Text = FoxUi.T("حساب تأیید شد و سرور اضافه شد.", "Account verified and profile added.");
        });
        refresh.Click += async (_, _) => await Run(async () => {
            if (accounts.SelectedItem is not FoxAccount account) return;
            account.Country = country.SelectedItem?.ToString() ?? "REC"; await FoxAccounts.SaveAsync(account);
            await FoxAccounts.RefreshAsync(account.Id, true, cts.Token); await Load(account.Id); await RefreshViews(); status.Text = FoxUi.T("سهمیه و ساب تازه شدند؛ یک سرور برای این حساب باقی می‌ماند.", "Allowance and subscription refreshed; this account retains one profile.");
        });
        connect.Click += async (_, _) => await Run(async () => {
            if (accounts.SelectedItem is not FoxAccount account || account.Pending) throw new FoxException("login_required", "Complete account sign-in first");
            account.Country = country.SelectedItem?.ToString() ?? "REC"; await FoxAccounts.SaveAsync(account); await FoxProfiles.SyncAsync(account); await RefreshViews();
            var sub = (await AppManager.Instance.SubItems()).First(s => s.Url == "dicode-fox://" + account.Id); var node = (await AppManager.Instance.ProfileItems(sub.Id)).Single();
            await main.ProfilesViewModel.SetDefaultServer(node.IndexId); await main.ConnectPoolProfileAsync(node.IndexId, cts.Token);
            status.Text = CoreManager.Instance.IsRunning ? FoxUi.T("روباه فعال شد؛ جزئیات و ترافیک در خانه دیده می‌شوند.", "Fox is active; connection details and traffic are shown on Home.") : FoxUi.T("اتصال برقرار نشد؛ گزارش را بررسی کنید.", "Connection did not start; check the log.");
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
        Content = new ScrollViewer { Content = new StackPanel { Margin = new Thickness(22), Spacing = 13, Children = {
            new PathIcon { Data = Geometry.Parse(FoxUi.Icon), Width = 32, Height = 32, HorizontalAlignment = HorizontalAlignment.Left },
            new TextBlock { Text = FoxUi.T("روباه", "Fox"), FontSize = 28, FontWeight = FontWeight.SemiBold },
            new TextBlock { Text = FoxUi.T("اتصال غیررسمی Firefox VPN با حساب شما. سهمیه و موقعیت‌های مجاز را Mozilla تعیین می‌کند؛ معمولاً تا ۵۰ گیگابایت در ماه برای حساب واجد شرایط. رمز عبور ذخیره نمی‌شود.", "Unofficial Firefox VPN connection using your account. Mozilla controls eligibility, locations and allowance, usually up to 50 GB/month for eligible accounts. Passwords are never stored."), TextWrapping = TextWrapping.Wrap },
            new TextBlock { Text = FoxUi.T("حساب‌های شما", "Your accounts"), FontWeight = FontWeight.SemiBold }, accounts, quota,
            new TextBlock { Text = FoxUi.T("موقعیت · REC: انتخاب پیشنهادی", "Location · REC: recommended selection") }, country, refresh, email, password, login, code, verify, status, connect, remove,
            new TextBlock { Text = FoxUi.T("TCP و DNS رمزگذاری‌شده پشتیبانی می‌شوند؛ UDP عمومی پشتیبانی نمی‌شود. حذف ساب آن را خودکار برنمی‌گرداند؛ دکمهٔ تازه‌سازی امکان افزودن دوباره را دارد.", "Supports TCP and encrypted DNS, not arbitrary UDP. Deleted subscriptions stay deleted until you explicitly sync them again."), TextWrapping = TextWrapping.Wrap, Opacity = 0.7 }
        } } };
    }
}
