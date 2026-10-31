using ServiceLib.Services;
using NativeWebView.Core;
using Avalonia.Threading;
using Avalonia.Layout;

namespace v2rayN.Desktop.Views;

public sealed class FoxBrowserWindow : Window
{
    public FoxBrowserWindow()
    {
        Title = FoxUi.T("ورود امن موزیلا", "Mozilla sign-in"); Width = 620; Height = 760; MinWidth = 320; MinHeight = 400;
        WindowStartupLocation = WindowStartupLocation.CenterOwner;
        var cancellation = new CancellationTokenSource(); var nonce = Guid.NewGuid().ToString("N");
        var status = new TextBlock { TextWrapping = TextWrapping.Wrap };
        var retry = new Button { Content = FoxUi.T("تلاش دوباره", "Retry"), IsVisible = false };
        var close = new Button { Content = FoxUi.T("بازگشت", "Back") };
        var host = new Grid();
        var bar = new StackPanel { Margin = new Thickness(12), Spacing = 8, Children = {
            new TextBlock { Text = "accounts.firefox.com", FontSize = 16 },
            new TextBlock { Text = FoxUi.T("ایمیل و رمز Firefox و کد تأیید را در صفحهٔ رسمی وارد کنید. ورود Google و Apple پشتیبانی نمی‌شود.", "Use your Firefox email, password and verification code on the official page. Google and Apple sign-in are not supported here."), TextWrapping = TextWrapping.Wrap },
            status, retry, close } };
        var layout = new Grid { RowDefinitions = new RowDefinitions("Auto,*") };
        layout.Children.Add(bar); Grid.SetRow(host, 1); layout.Children.Add(host); Content = layout;
        NativeWebView.Controls.NativeWebView? web = null; bool busy = false; bool disposed = false;
        close.Click += (_, _) => Close();
        Closed += (_, _) => { disposed = true; cancellation.Cancel(); web?.Dispose(); };
        retry.Click += async (_, _) => { try { if (web is not null && !busy && !disposed) await web.ExecuteScriptAsync("window.__dicodeFoxRetry && window.__dicodeFoxRetry()", cancellation.Token); } catch (Exception) { } };
        Opened += async (_, _) => {
            try {
                if (OperatingSystem.IsWindows()) NativeWebView.Platform.Windows.NativeWebViewPlatformWindowsModule.RegisterDefault();
                else if (OperatingSystem.IsMacOS()) NativeWebView.Platform.macOS.NativeWebViewPlatformMacOSModule.RegisterDefault();
                else NativeWebView.Platform.Linux.NativeWebViewPlatformLinuxModule.RegisterDefault();
                web = new NativeWebView.Controls.NativeWebView { IsDevToolsEnabled = false, IsContextMenuEnabled = false };
                web.InstanceConfiguration.ControllerOptions.IsInPrivateModeEnabled = true;
                web.InstanceConfiguration.ControllerOptions.IsPasswordAutosaveEnabled = false;
                web.InstanceConfiguration.ControllerOptions.IsGeneralAutofillEnabled = false;
                web.InstanceConfiguration.ControllerOptions.RedactNavigationDetails = true;
                web.InstanceConfiguration.EnvironmentOptions.UserDataFolder = Path.Combine(FoxAccounts.Folder, "Browser");
                web.InstanceConfiguration.DocumentStartScripts.Add(new NativeWebViewDocumentStartScript(FoxBrowserProtocol.Script(nonce), NativeWebViewScriptFrameScope.MainFrame));
                web.NavigationStarted += (_, e) => { if (!FoxBrowserProtocol.IsTrusted(e.Uri?.ToString())) e.Cancel = true; };
                web.NewWindowRequested += (_, e) => { e.Handled = true; };
                web.WebMessageReceived += (_, e) => Dispatcher.UIThread.Post(async () => {
                    if (busy || disposed) return;
                    string? payload = e.Message ?? e.Json;
                    // WebView2 reports a JS string as JSON; decode once, never log it.
                    if (payload?.StartsWith('"') == true) { try { payload = System.Text.Json.JsonSerializer.Deserialize<string>(payload); } catch { return; } }
                    var session = FoxBrowserProtocol.Parse(web.CurrentUrl?.ToString(), payload, nonce);
                    if (session is null) return;
                    busy = true; retry.IsVisible = false; close.IsEnabled = false;
                    status.Text = FoxUi.T("در حال تأیید نشست امن…", "Verifying account session…");
                    try {
                        var account = await FoxAccounts.CompleteBrowserLoginAsync(session.Value.Email, session.Value.Session, cancellation.Token);
                        if (!disposed) Close(account);
                    } catch (OperationCanceledException) { }
                    catch (Exception error) {
                        if (!disposed) {
                            status.Text = error is FoxException f && f.Code == "session_unconfirmed" ? FoxUi.T("تأیید ایمیل یا ورود دومرحله‌ای را در همین صفحه کامل کنید.", "Complete email or two-factor verification on this page.") : FoxUi.Error(error);
                            retry.IsVisible = true;
                            try { await web.ExecuteScriptAsync("window.__dicodeFoxWaiting && window.__dicodeFoxWaiting()", cancellation.Token); } catch (Exception) { }
                        }
                    } finally { busy = false; close.IsEnabled = true; }
                });
                host.Children.Add(web);
                await web.InitializeAsync(cancellation.Token);
                web.SetUserAgent("Mozilla/5.0 (X11; Linux x86_64; rv:132.0) Gecko/20100101 Firefox/132.0");
                web.Navigate(FoxBrowserProtocol.LoginUrl);
            } catch (OperationCanceledException) { }
            catch (Exception) {
                status.Text = FoxUi.T("مرورگر داخلی آماده نشد. در ویندوز Microsoft Edge WebView2 Runtime و در لینوکس بستهٔ libwebkit2gtk-4.1-0 را نصب/به‌روز کنید و دوباره تلاش کنید.", "The embedded browser could not start. Install/update Microsoft Edge WebView2 Runtime on Windows, or libwebkit2gtk-4.1-0 on Linux, then retry.");
            }
        };
    }
}
