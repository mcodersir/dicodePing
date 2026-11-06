using ServiceLib.Services;
using NativeWebView.Core;
using Avalonia.Threading;
using Avalonia.Layout;

namespace v2rayN.Desktop.Views;

public sealed class FoxBrowserWindow : Window
{
    public static void ConfigureSignInProxy(NativeWebView.Controls.NativeWebView web, string address)
    {
        web.InstanceConfiguration.EnvironmentOptions.Proxy = new NativeWebViewProxyOptions { Server = "http://" + address };
    }
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
        NativeWebView.Controls.NativeWebView? web = null; bool busy = false; bool disposed = false; (string Email, string Session)? pending = null;
        ServiceLib.Services.ProcessService? signInProxy = null;
        close.Click += (_, _) => Close();
        Closed += async (_, _) => { disposed = true; pending = null; cancellation.Cancel(); web?.Dispose(); if (signInProxy is not null) { await signInProxy.StopAsync(); signInProxy.Dispose(); } };
        retry.Click += async (_, _) => { try { if (web is not null && !busy && !disposed) await web.ExecuteScriptAsync("window.__dicodeFoxRetry && window.__dicodeFoxRetry()", cancellation.Token); } catch (Exception) { } };
        Opened += async (_, _) => {
            try {
                var proxy = await FoxAccounts.OpenSignInProxyAsync(cancellation.Token);
                signInProxy = proxy.Process;
                if (OperatingSystem.IsWindows()) NativeWebView.Platform.Windows.NativeWebViewPlatformWindowsModule.RegisterDefault();
                else if (OperatingSystem.IsMacOS()) NativeWebView.Platform.macOS.NativeWebViewPlatformMacOSModule.RegisterDefault();
                else NativeWebView.Platform.Linux.NativeWebViewPlatformLinuxModule.RegisterDefault();
                web = new NativeWebView.Controls.NativeWebView { IsDevToolsEnabled = false, IsContextMenuEnabled = false };
                web.InstanceConfiguration.ControllerOptions.IsInPrivateModeEnabled = true;
                web.InstanceConfiguration.ControllerOptions.IsPasswordAutosaveEnabled = false;
                web.InstanceConfiguration.ControllerOptions.IsGeneralAutofillEnabled = false;
                web.InstanceConfiguration.ControllerOptions.RedactNavigationDetails = true;
                web.InstanceConfiguration.EnvironmentOptions.UserDataFolder = Path.Combine(FoxAccounts.Folder, "Browser");
                ConfigureSignInProxy(web, proxy.Address);
                web.InstanceConfiguration.DocumentStartScripts.Add(new NativeWebViewDocumentStartScript(FoxBrowserProtocol.Script(nonce), NativeWebViewScriptFrameScope.MainFrame));
                web.NavigationStarted += (_, e) => { if (!FoxBrowserProtocol.IsTrusted(e.Uri?.ToString())) e.Cancel = true; };
                web.NewWindowRequested += (_, e) => { e.Handled = true; };
                web.WebMessageReceived += (_, e) => Dispatcher.UIThread.Post(async () => {
                    if (disposed) return;
                    string? payload = e.Message ?? e.Json;
                    // WebView2 reports a JS string as JSON; decode once, never log it.
                    if (payload?.StartsWith('"') == true) { try { payload = System.Text.Json.JsonSerializer.Deserialize<string>(payload); } catch { return; } }
                    var captured = FoxBrowserProtocol.ParsePending(web.CurrentUrl?.ToString(), payload, nonce);
                    if (captured is not null) { pending = captured; return; }
                    if (FoxBrowserProtocol.IsReady(web.CurrentUrl?.ToString(), payload, nonce)) {
                        if (pending is not null) {
                            var restore = "window.__dicodeFoxRestore && window.__dicodeFoxRestore(" + System.Text.Json.JsonSerializer.Serialize(pending.Value.Session) + "," + System.Text.Json.JsonSerializer.Serialize(pending.Value.Email) + ")";
                            try { await web.ExecuteScriptAsync(restore, cancellation.Token); } catch (OperationCanceledException) { }
                            catch (Exception) { status.Text = FoxUi.T("صفحهٔ ورود آمادهٔ ادامه نیست؛ دوباره تلاش کنید.", "The sign-in page is not ready to continue. Retry."); retry.IsVisible = true; }
                        }
                        return;
                    }
                    if (FoxBrowserProtocol.IsProgress(web.CurrentUrl?.ToString(), payload, nonce)) {
                        status.Text = FoxUi.T("در حال دریافت مجوز حساب از موزیلا…", "Requesting the account grant from Mozilla…");
                        return;
                    }
                    if (FoxBrowserProtocol.ParseError(web.CurrentUrl?.ToString(), payload, nonce) is string code) {
                        status.Text = code == "session_unconfirmed"
                            ? FoxUi.T("کد ایمیل یا تأیید دومرحله‌ای را در همین صفحه کامل کنید.", "Complete email or two-factor verification on this page.")
                            : code == "verification_required"
                            ? FoxUi.T("موزیلا درخواست توکن این مرورگر را رد کرد. نشست ذخیره نشد؛ پس از رفع بررسی امنیتی، تلاش دوباره را بزنید.", "Mozilla refused this browser's token request. No session was saved. Complete its security check, then retry.")
                            : FoxUi.T("تبادل توکن مرورگر کامل نشد؛ اتصال را بررسی کنید و دوباره تلاش کنید.", "Browser token exchange did not complete. Check the connection and retry.");
                        retry.IsVisible = true; return;
                    }
                    if (busy) return;
                    var session = FoxBrowserProtocol.Parse(web.CurrentUrl?.ToString(), payload, nonce);
                    var grant = FoxBrowserProtocol.ParseGrant(web.CurrentUrl?.ToString(), payload, nonce);
                    if (session is null && grant is null) return;
                    busy = true; retry.IsVisible = false; close.IsEnabled = true;
                    status.Text = FoxUi.T("در حال تأیید نشست امن…", "Verifying account session…");
                    try {
                        var account = grant is not null
                            ? await FoxAccounts.CompleteBrowserGrantAsync(grant, cancellation.Token)
                            : await FoxAccounts.CompleteBrowserLoginAsync(session!.Value.Email, session.Value.Session, cancellation.Token);
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
                web.SetUserAgent("Mozilla/5.0 (X11; Linux x86_64; rv:158.0) Gecko/20100101 Firefox/158.0");
                web.Navigate(FoxBrowserProtocol.LoginUrl);
            } catch (OperationCanceledException) { }
            catch (Exception) {
                status.Text = FoxUi.T("مرورگر داخلی آماده نشد. در ویندوز Microsoft Edge WebView2 Runtime و در لینوکس بستهٔ libwebkit2gtk-4.1-0 را نصب/به‌روز کنید و دوباره تلاش کنید.", "The embedded browser could not start. Install/update Microsoft Edge WebView2 Runtime on Windows, or libwebkit2gtk-4.1-0 on Linux, then retry.");
            }
        };
    }
}
