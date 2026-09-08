using ServiceLib.Services;
using Avalonia.Input.Platform;
using System.Collections.ObjectModel;

namespace v2rayN.Desktop.Views;

public sealed class ServerPoolWindow : Window
{
    private CancellationTokenSource? _stop;
    private CancellationTokenSource? _abort;
    private bool _testing;
    public ServerPoolWindow(MainWindowViewModel main)
    {
        Title = "استخر سرورها";
        Width = 820; Height = 680; MinWidth = 500; MinHeight = 440;
        WindowStartupLocation = WindowStartupLocation.CenterOwner;
        var status = new TextBlock { Text = "آمادهٔ جمع‌آوری", TextWrapping = TextWrapping.Wrap };
        var stage = new TextBlock { Text = "اتصال فعال ← fallback ساب پیش‌فرض ← کانال‌ها ← آزمون ← ذخیره", FontSize = 16, TextWrapping = TextWrapping.Wrap };
        var counts = new TextBlock { Text = "هر پاسخ باید معتبر و حداکثر ۹۰۰ میلی‌ثانیه باشد.", TextWrapping = TextWrapping.Wrap };
        var bar = new ProgressBar { Minimum = 0, Maximum = 100, Height = 6 };
        var rows = new ListBox();
        var history = new ObservableCollection<string>();
        var logs = new ListBox { ItemsSource = history, FontFamily = FontFamily.Parse("monospace"), FontSize = 12 };
        var follow = new CheckBox { Content = "دنبال‌کردن لاگ", IsChecked = true };
        var start = new Button { Content = "شروع جمع‌آوری" };
        var cancel = new Button { Content = "توقف", IsEnabled = false };
        var copy = new Button { Content = "کپی لاگ" };
        var clear = new Button { Content = "پاک‌کردن لاگ" };
        var target = new NumericUpDown { Minimum = ServerPoolOptions.MinTargetCount,
            Maximum = ServerPoolOptions.MaxTargetCount, Increment = 1, Value = 20, Width = 100 };
        var rounds = new NumericUpDown { Minimum = ServerPoolOptions.MinTestRounds,
            Maximum = ServerPoolOptions.MaxTestRounds, Increment = 1, Value = 3, Width = 100 };
        var settings = new StackPanel { Orientation = Avalonia.Layout.Orientation.Horizontal, Spacing = 10,
            Children = { new TextBlock { Text = "تعداد سرور موفق هدف", VerticalAlignment = Avalonia.Layout.VerticalAlignment.Center }, target,
                new TextBlock { Text = "نوبت تست هر سرور", VerticalAlignment = Avalonia.Layout.VerticalAlignment.Center }, rounds } };
        var tabs = new TabControl { ItemsSource = new[] {
            new TabItem { Header = "لاگ زنده", Content = logs }, new TabItem { Header = "سرورهای ذخیره‌شده", Content = rows }
        }};
        var layout = new Grid { RowDefinitions = new RowDefinitions("Auto,Auto,Auto,Auto,Auto,Auto,*"), Margin = new Thickness(24), RowSpacing = 12 };
        Control[] sections = [new TextBlock { Text = Title, FontSize = 26 }, stage,
            settings,
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
            _testing = update.Stage == "آزمون";
            var changed = stage.Text != update.Stage;
            stage.Text = update.Stage; status.Text = update.Message;
            if (changed) { bar.IsIndeterminate = update.Total == 0 && _stop != null; counts.Text = "در حال اجرا…"; }
            if (update.Total > 0) {
                bar.IsIndeterminate = false;
                bar.Value = 100d * update.Completed / update.Total;
                counts.Text = update.Stage == "جمع‌آوری"
                    ? $"{update.Completed}/{update.Total} · کاندید: {update.Passed} · خطا: {update.Failed}"
                    : $"{update.Completed}/{update.Total} · موفق: {update.Passed}{(update.Target > 0 ? $"/{update.Target}" : "")} · ناموفق: {update.Failed}";
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
        cancel.Click += (_, _) => {
            _stop?.Cancel(); cancel.IsEnabled = false;
            status.Text = _testing
                ? "در حال توقف نرم؛ سرورهای موفق تکمیل‌شده ذخیره خواهند شد…"
                : "در حال توقف جمع‌آوری…";
            Log(status.Text);
        };
        Closing += (_, _) => { _abort?.Cancel(); _stop?.Cancel(); };
        start.Click += async (_, _) =>
        {
            start.IsEnabled = false; cancel.IsEnabled = true; target.IsEnabled = false; rounds.IsEnabled = false; tabs.SelectedIndex = 0;
            using var stop = new CancellationTokenSource(); using var abort = new CancellationTokenSource();
            _stop = stop; _abort = abort;
            var options = new ServerPoolOptions(Convert.ToInt32(target.Value ?? 20), Convert.ToInt32(rounds.Value ?? 3)).Normalize();
            Log($"شروع اجرای جدید · 4.0.0 · هدف {options.TargetCount} سرور · {options.TestRounds} نوبت");
            try
            {
                await new ServerPoolService().RunAsync((profile, token) => main.ConnectPoolProfileAsync(profile.IndexId, token),
                    new Progress<PoolProgress>(Update), options, stop.Token, abort.Token);
                await main.ProfilesViewModel.RefreshSubscriptions();
                await main.ProfilesViewModel.RefreshServers();
                await Refresh();
            }
            catch (OperationCanceledException) { Update(new("متوقف", "عملیات پیش از تکمیل یک نتیجهٔ موفق متوقف شد؛ استخر قبلی حفظ شد.")); }
            catch (Exception ex) { Update(new("خطا", ex.Message)); }
            finally {
                _stop = null; _abort = null; _testing = false; start.Content = "اجرای دوباره";
                start.IsEnabled = true; target.IsEnabled = true; rounds.IsEnabled = true;
                cancel.IsEnabled = false; bar.IsIndeterminate = false;
            }
        };
    }
}
