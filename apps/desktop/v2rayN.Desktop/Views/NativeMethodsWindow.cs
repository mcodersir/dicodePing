using Avalonia;
using Avalonia.Controls;
using Avalonia.Layout;
using ServiceLib.Services;

namespace v2rayN.Desktop.Views;

public sealed class NativeMethodsWindow : Window
{
    public NativeMethodsWindow(MainWindowViewModel main)
    {
        Title = "DicodePing · روش‌های اتصال"; Width = 580; Height = 650; MinWidth = 320;
        WindowStartupLocation = WindowStartupLocation.CenterOwner;
        var kinds = new[] { "snell", "anytls", "ssh", "openconnect", "openvpn-client", "socks" };
        var kind = new ComboBox { ItemsSource = new[] { "Snell 4", "AnyTLS", "SSH", "Cisco / OpenConnect", "OpenVPN", "ابزار مستقل · SOCKS5" }, SelectedIndex = 0, HorizontalAlignment = HorizontalAlignment.Stretch };
        var name = new TextBox { PlaceholderText = "نام اتصال / Connection name" };
        var server = new TextBox { PlaceholderText = "Server hostname / IP" };
        var port = new NumericUpDown { Minimum = 1, Maximum = 65535, Value = 443 };
        var username = new TextBox { PlaceholderText = "Username" };
        var password = new TextBox { PlaceholderText = "Password / PSK", PasswordChar = '●' };
        var extraLabel = new TextBlock { TextWrapping = Avalonia.Media.TextWrapping.Wrap };
        var extra = new TextBox { AcceptsReturn = true, MinHeight = 70, MaxHeight = 150, PlaceholderText = "SNI / SSH host key / CA PEM" };
        var status = new TextBlock { TextWrapping = Avalonia.Media.TextWrapping.Wrap };
        var save = new Button { Content = ResUI.TbConfirm, HorizontalAlignment = HorizontalAlignment.Stretch };
        void Update()
        {
            var k = kinds[kind.SelectedIndex]; username.IsVisible = k is "ssh" or "openconnect" or "openvpn-client" or "socks";
            extra.IsVisible = k is not ("snell" or "socks"); port.Value = k == "socks" ? 1080 : k == "ssh" ? 22 : k == "openvpn-client" ? 1194 : 443;
            extraLabel.Text = k switch { "socks" => "برای MasterDNS / DNSTT / VayDNS / MHR / MHR-CFW / MITM fronting / SNI Spoofing: ابتدا ابزار مستقل را راه‌اندازی کنید و آدرس پروکسی SOCKS5 آن را وارد کنید. این ابزارها هستهٔ داخلی برنامه نیستند. گواهی ریشه خودکار نصب نمی‌شود.", "ssh" => "کلید میزبان SSH (پیشنهادی) / SSH host key", "openvpn-client" => "گواهی CA سرور (PEM)؛ تنظیمات گواهی کاربر را از ویرایش JSON اضافه کنید.", "openconnect" => "گواهی CA خصوصی (اختیاری) / Private CA certificate", _ => "نام TLS سرور / TLS server name" };
        }
        kind.SelectionChanged += (_, _) => Update(); Update();
        save.Click += async (_, _) => {
            save.IsEnabled = false;
            var path = Utils.GetTempPath("native-" + Guid.NewGuid() + ".json");
            try {
                var json = NativeProfileTemplates.Build(kinds[kind.SelectedIndex], server.Text ?? "", (int)(port.Value ?? 443), username.Text ?? "", password.Text ?? "", extra.Text ?? "");
                await File.WriteAllTextAsync(path, json);
                await NativeConfigurationValidator.ValidateAsync(path);
                var node = new ProfileItem { Address = path, CoreType = ECoreType.sing_box, PreSocksPort = AppManager.Instance.GetLocalPort(EInboundProtocol.mixed), Remarks = name.Text.IsNotEmpty() ? name.Text : kinds[kind.SelectedIndex], Subid = AppManager.Instance.Config.SubIndexId };
                if (await ConfigHandler.AddCustomServer(AppManager.Instance.Config, node, true) != 0) throw new IOException("Could not save profile");
                await main.ProfilesViewModel.RefreshServersBiz(); Close();
            } catch (Exception error) { status.Text = error.Message; }
            finally { save.IsEnabled = true; if (File.Exists(path)) File.Delete(path); }
        };
        var scan = new Button { Content = "CF IP Scanner", HorizontalAlignment = HorizontalAlignment.Stretch };
        scan.Click += (_, _) => new CloudflareScannerWindow().ShowDialog(this);
        Content = new ScrollViewer { Content = new StackPanel { Margin = new Thickness(20), Spacing = 12, Children = {
            new TextBlock { Text = "روش‌های اتصال بیشتر", FontSize = 24 },
            new TextBlock { Text = "پروفایل‌ها با هستهٔ داخلی sing-box اجرا می‌شوند. تنظیمات پیشرفتهٔ سرور را در JSON پروفایل ویرایش کنید.", TextWrapping = Avalonia.Media.TextWrapping.Wrap }, kind, name, server, port, username, password, extraLabel, extra, status, save, scan } } };
    }
}
public sealed class CloudflareScannerWindow : Window
{
    public CloudflareScannerWindow()
    {
        Title = "CF IP Scanner"; Width = 520; Height = 580; MinWidth = 320;
        var addresses = new TextBox { AcceptsReturn = true, Height = 180, PlaceholderText = "Cloudflare IP addresses, one per line" };
        var results = new TextBox { AcceptsReturn = true, IsReadOnly = true, Height = 190 };
        var progress = new ProgressBar { Minimum = 0, Maximum = 100, Height = 6 };
        var run = new Button { Content = "Scan HTTPS" }; var stop = new Button { Content = "Stop" }; CancellationTokenSource? cancellation = null;
        stop.Click += (_, _) => cancellation?.Cancel(); Closed += (_, _) => cancellation?.Cancel();
        run.Click += async (_, _) => {
            if (cancellation is not null) return;
            using var cts = new CancellationTokenSource(); cancellation = cts; run.IsEnabled = false;
            try { var found = await CloudflareScanner.ScanAsync((addresses.Text ?? "").Split('\n'), (done,total) => Avalonia.Threading.Dispatcher.UIThread.Post(() => progress.Value = total == 0 ? 0 : 100d*done/total), cts.Token);
                results.Text = string.Join(Environment.NewLine, found.Select(x => $"{x.Address}  {(x.Latency.HasValue ? x.Latency + " ms" : x.Error)}")); }
            catch (OperationCanceledException) { results.Text = "Cancelled"; }
            catch (Exception e) { results.Text = e.Message; }
            finally { cancellation = null; run.IsEnabled = true; }
        };
        Content = new ScrollViewer { Content = new StackPanel { Margin = new Thickness(20), Spacing = 12, Children = { new TextBlock { Text = "تست واقعی HTTPS با اعتبارسنجی گواهی؛ نتیجه، کیفیت اتصال به همهٔ سرورها را تضمین نمی‌کند.", TextWrapping = Avalonia.Media.TextWrapping.Wrap }, addresses, run, stop, progress, results } } };
    }
}
