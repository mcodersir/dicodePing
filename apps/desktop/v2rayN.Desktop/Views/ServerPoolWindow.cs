using ServiceLib.Services;
using Avalonia.Input.Platform;
using System.Collections.ObjectModel;

namespace v2rayN.Desktop.Views;

public sealed class ServerPoolWindow : Window
{
    private CancellationTokenSource? _run;
    public ServerPoolWindow(MainWindowViewModel main)
    {
        Title = "استخر سرورها";
        Width = 820; Height = 680; MinWidth = 500; MinHeight = 440;
        WindowStartupLocation = WindowStartupLocation.CenterOwner;
        var status = new TextBlock { Text = "آمادهٔ جمع‌آوری", TextWrapping = TextWrapping.Wrap };
        var stage = new TextBlock { Text = "ساب پیش‌فرض ← اتصال ← کانال‌ها ← آزمون ← ذخیره", FontSize = 16, TextWrapping = TextWrapping.Wrap };
        var counts = new TextBlock { Text = "سه پاسخ معتبر · حداکثر ۹۰۰ میلی‌ثانیه", TextWrapping = TextWrapping.Wrap };
        var bar = new ProgressBar { Minimum = 0, Maximum = 100, Height = 6 };
        var rows = new ListBox();
        var history = new ObservableCollection<string>();
        var logs = new ListBox { ItemsSource = history, FontFamily = FontFamily.Parse("monospace"), FontSize = 12 };
        var follow = new CheckBox { Content = "دنبال‌کردن لاگ", IsChecked = true };
        var start = new Button { Content = "شروع جمع‌آوری" };
        var cancel = new Button { Content = "توقف", IsEnabled = false };
        var copy = new Button { Content = "کپی لاگ" };
        var clear = new Button { Content = "پاک‌کردن لاگ" };
        var tabs = new TabControl { ItemsSource = new[] {
            new TabItem { Header = "لاگ زنده", Content = logs }, new TabItem { Header = "سرورهای ذخیره‌شده", Content = rows }
        }};
        var layout = new Grid { RowDefinitions = new RowDefinitions("Auto,Auto,Auto,Auto,Auto,*"), Margin = new Thickness(24), RowSpacing = 12 };
        Control[] sections = [new TextBlock { Text = Title, FontSize = 26 }, stage,
            new StackPanel { Orientation = Avalonia.Layout.Orientation.Horizontal, Spacing = 8, Children = { start, cancel, copy, clear } },
            new StackPanel { Spacing = 8, Children = { status, counts, bar } }, follow, tabs];
        for (var i = 0; i < sections.Length; i++) { Grid.SetRow(sections[i], i); layout.Children.Add(sections[i]); }
        Content = layout;
        void Log(string text)
        {
            history.Add($"{DateTime.Now:HH:mm:ss}  {text}");
            while (history.Count > 300) history.RemoveAt(0);
            if (follow.IsChecked == true) logs.ScrollIntoView(history.Last());
        }
        void Update(PoolProgress update)
        {
            var changed = stage.Text != update.Stage;
            stage.Text = update.Stage; status.Text = update.Message;
            if (changed) { bar.IsIndeterminate = update.Total == 0 && _run != null; counts.Text = "در حال اجرا…"; }
            if (update.Total > 0) {
                bar.IsIndeterminate = false;
                bar.Value = 100d * update.Completed / update.Total;
                counts.Text = $"{update.Completed}/{update.Total} · {(update.Stage == "جمع‌آوری" ? "کاندید" : "پذیرفته")}: {update.Passed} · خطا: {update.Failed}";
            }
            Log($"[{update.Stage}] {update.Message}" + (update.Total > 0 ? $" · {update.Completed}/{update.Total}" : ""));
        }
        async Task Refresh()
        {
            var delays = (await ProfileExManager.Instance.GetProfileExs()).ToDictionary(x => x.IndexId, x => x.Delay);
            rows.ItemsSource = (await AppManager.Instance.ProfileItems(ServerPoolService.PoolId) ?? [])
                .Select(p => $"{p.Remarks} · {delays.GetValueOrDefault(p.IndexId)} ms").ToList();
        }
        Opened += async (_, _) => {
            try { await ServerPoolService.EnsureSubscriptionAsync(); await main.ProfilesViewModel.RefreshSubscriptions(); await Refresh(); }
            catch (Exception ex) { Update(new("خطا", ex.Message)); }
        };
        copy.Click += async (_, _) => { if (Clipboard != null) await Clipboard.SetTextAsync(string.Join(Environment.NewLine, history)); };
        clear.Click += (_, _) => history.Clear();
        cancel.Click += (_, _) => { _run?.Cancel(); cancel.IsEnabled = false; status.Text = "در حال توقف و آزادسازی هسته‌های آزمون…"; Log(status.Text); };
        Closing += (_, _) => _run?.Cancel();
        start.Click += async (_, _) =>
        {
            start.IsEnabled = false; cancel.IsEnabled = true; tabs.SelectedIndex = 0;
            using var cts = new CancellationTokenSource(); _run = cts;
            Log("شروع اجرای جدید · 3.9.0 revision 3");
            try
            {
                await new ServerPoolService().RunAsync(profile => main.ConnectPoolProfileAsync(profile.IndexId, cts.Token),
                    new Progress<PoolProgress>(Update), cts.Token);
                await main.ProfilesViewModel.RefreshSubscriptions();
                await main.ProfilesViewModel.RefreshServers();
                await Refresh();
            }
            catch (OperationCanceledException) { Update(new("متوقف", "جمع‌آوری متوقف شد؛ استخر قبلی حفظ شد.")); }
            catch (Exception ex) { Update(new("خطا", ex.Message)); }
            finally { _run = null; start.Content = "اجرای دوباره"; start.IsEnabled = true; cancel.IsEnabled = false; bar.IsIndeterminate = false; }
        };
    }
}
