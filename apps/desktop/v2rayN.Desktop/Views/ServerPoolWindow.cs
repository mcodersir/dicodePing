using ServiceLib.Services;

namespace v2rayN.Desktop.Views;

public sealed class ServerPoolWindow : Window
{
    private CancellationTokenSource? _run;
    public ServerPoolWindow(MainWindowViewModel main)
    {
        Title = "استخر سرورها";
        Width = 660; Height = 520; MinWidth = 420; MinHeight = 380;
        WindowStartupLocation = WindowStartupLocation.CenterOwner;
        var status = new TextBlock { Text = "آمادهٔ جمع‌آوری", TextWrapping = TextWrapping.Wrap };
        var list = new ListBox { Height = 220 };
        var start = new Button { Content = "جمع‌آوری و بروزرسانی استخر" };
        var cancel = new Button { Content = "توقف", IsEnabled = false };
        Content = new StackPanel
        {
            Margin = new Thickness(24), Spacing = 16,
            Children =
            {
                new TextBlock { Text = Title, FontSize = 24 },
                new TextBlock { Text = "اتصال خودکار از ساب پیش‌فرض؛ حداکثر ۴ کانفیگ از پیام‌های ۷ روز اخیر هر کانال. فقط کانفیگ‌هایی با سه پاسخ معتبر تا ۹۰۰ میلی‌ثانیه ذخیره می‌شوند.", TextWrapping = TextWrapping.Wrap },
                new StackPanel { Orientation = Avalonia.Layout.Orientation.Horizontal, Spacing = 12, Children = { start, cancel } },
                status, list
            }
        };
        async Task Refresh() => list.ItemsSource = (await AppManager.Instance.ProfileItems(ServerPoolService.PoolId) ?? [])
            .Select(p => p.Remarks).ToList();
        Opened += async (_, _) => await Refresh();
        cancel.Click += (_, _) => { _run?.Cancel(); status.Text = "در حال توقف…"; };
        Closing += (_, _) => _run?.Cancel();
        start.Click += async (_, _) =>
        {
            start.IsEnabled = false; cancel.IsEnabled = true;
            using var cts = new CancellationTokenSource(); _run = cts;
            try
            {
                await new ServerPoolService().RunAsync(async profile =>
                {
                    await main.ProfilesViewModel.SetDefaultServer(profile.IndexId);
                    main.ProfilesViewModel.ConnectionStartRequested.Publish();
                    for (var i = 0; i < 100 && !CoreManager.Instance.IsRunning; i++) await Task.Delay(100, cts.Token);
                    if (!CoreManager.Instance.IsRunning) throw new InvalidOperationException("اتصال برقرار نشد؛ گزارش اتصال را بررسی کنید.");
                }, new Progress<string>(text => status.Text = text), cts.Token);
                await main.ProfilesViewModel.RefreshSubscriptions();
                await main.ProfilesViewModel.RefreshServers();
                await Refresh();
            }
            catch (OperationCanceledException) { status.Text = "متوقف شد؛ استخر قبلی حفظ شد."; }
            catch (Exception ex) { status.Text = ex.Message; }
            finally { _run = null; start.IsEnabled = true; cancel.IsEnabled = false; }
        };
    }
}
