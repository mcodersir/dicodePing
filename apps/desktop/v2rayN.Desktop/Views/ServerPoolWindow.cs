using ServiceLib.Services;
using Avalonia.Input.Platform;
using System.Collections.ObjectModel;

namespace v2rayN.Desktop.Views;

public sealed class ServerPoolWindow : Window
{
    private CancellationTokenSource? _stop;
    private CancellationTokenSource? _abort;
    private bool _testing;

    private static string StageDisplay(string stage) => stage switch
    {
        "Active route" => ResUI.DicodePoolStageActiveRoute,
        "Pool" => ResUI.DicodePoolStagePool,
        "Default subscription" => ResUI.DicodePoolStageDefaultSub,
        "Connection" => ResUI.DicodePoolStageConnection,
        "Channels" => ResUI.DicodePoolStageChannels,
        "Collecting" => ResUI.DicodePoolStageCollecting,
        "Test" => ResUI.DicodePoolStageTest,
        "Save" => ResUI.DicodePoolStageSave,
        "Stopped" => ResUI.DicodePoolStageStopped,
        "Done" => ResUI.DicodePoolStageDone,
        _ => stage,
    };

    public ServerPoolWindow(MainWindowViewModel main)
    {
        Title = ResUI.DicodeServerPool;
        FlowDirection = string.Equals(AppManager.Instance.Config?.UiItem?.CurrentLanguage, "fa", StringComparison.OrdinalIgnoreCase)
            ? FlowDirection.RightToLeft
            : FlowDirection.LeftToRight;
        Width = 820; Height = 680; MinWidth = 500; MinHeight = 440;
        WindowStartupLocation = WindowStartupLocation.CenterOwner;
        var status = new TextBlock { Text = ResUI.DicodePoolReady, TextWrapping = TextWrapping.Wrap };
        var stage = new TextBlock { Text = ResUI.DicodePoolPipeline, FontSize = 16, TextWrapping = TextWrapping.Wrap };
        var counts = new TextBlock { Text = ResUI.DicodePoolRequirement, TextWrapping = TextWrapping.Wrap };
        var bar = new ProgressBar { Minimum = 0, Maximum = 100, Height = 6 };
        var rows = new ListBox();
        var history = new ObservableCollection<string>();
        var logs = new ListBox { ItemsSource = history, FontFamily = FontFamily.Parse("monospace"), FontSize = 12 };
        var follow = new CheckBox { Content = ResUI.DicodePoolFollowLog, IsChecked = true };
        var start = new Button { Content = ResUI.DicodePoolStart };
        var cancel = new Button { Content = ResUI.DicodePoolStop, IsEnabled = false };
        var copy = new Button { Content = ResUI.DicodePoolCopyLog };
        var clear = new Button { Content = ResUI.DicodePoolClearLog };
        var target = new NumericUpDown { Minimum = ServerPoolOptions.MinTargetCount,
            Maximum = ServerPoolOptions.MaxTargetCount, Increment = 1, Value = 20, Width = 100 };
        var rounds = new NumericUpDown { Minimum = ServerPoolOptions.MinTestRounds,
            Maximum = ServerPoolOptions.MaxTestRounds, Increment = 1, Value = 3, Width = 100 };
        var settings = new StackPanel { Orientation = Avalonia.Layout.Orientation.Horizontal, Spacing = 10,
            Children = { new TextBlock { Text = ResUI.DicodePoolTarget, VerticalAlignment = Avalonia.Layout.VerticalAlignment.Center }, target,
                new TextBlock { Text = ResUI.DicodePoolRounds, VerticalAlignment = Avalonia.Layout.VerticalAlignment.Center }, rounds } };
        var tabs = new TabControl { ItemsSource = new[] {
            new TabItem { Header = ResUI.DicodePoolLiveLog, Content = logs }, new TabItem { Header = ResUI.DicodePoolSavedServers, Content = rows }
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
            _testing = update.Stage.Equals("Test", StringComparison.OrdinalIgnoreCase);
            var changed = stage.Text != update.Stage;
            stage.Text = update.Stage; status.Text = update.Message;
            if (changed) { bar.IsIndeterminate = update.Total == 0 && _stop != null; counts.Text = ResUI.DicodePoolRunning; }
            if (update.Total > 0) {
                bar.IsIndeterminate = false;
                bar.Value = 100d * update.Completed / update.Total;
                counts.Text = update.Stage.Equals("Collecting", StringComparison.OrdinalIgnoreCase)
                    ? string.Format(ResUI.DicodePoolCountsCollecting, update.Completed, update.Total, update.Passed, update.Failed)
                    : string.Format(ResUI.DicodePoolCountsTest, update.Completed, update.Total, update.Passed + (update.Target > 0 ? $"/{update.Target}" : ""), update.Failed);
            }
            Log($"[{StageDisplay(update.Stage)}] {update.Message}" + (update.Total > 0 ? $" · {update.Completed}/{update.Total}" : ""));
        }
        async Task Refresh()
        {
            var delays = (await ProfileExManager.Instance.GetProfileExs()).ToDictionary(x => x.IndexId, x => x.Delay);
            rows.ItemsSource = (await AppManager.Instance.ProfileItems(ServerPoolService.PoolId) ?? [])
                .Select(p => $"{p.Remarks} · {delays.GetValueOrDefault(p.IndexId)} ms").ToList();
        }
        Opened += async (_, _) => {
            try { await ServerPoolService.EnsureSubscriptionAsync(); await main.ProfilesViewModel.RefreshSubscriptions(); await Refresh(); }
            catch (Exception ex) { Update(new(ResUI.DicodePoolError, ex.Message)); }
        };
        copy.Click += async (_, _) => { if (Clipboard != null) await Clipboard.SetTextAsync(string.Join(Environment.NewLine, history)); };
        clear.Click += (_, _) => history.Clear();
        cancel.Click += (_, _) => {
            _stop?.Cancel(); cancel.IsEnabled = false;
            status.Text = _testing
                ? ResUI.DicodePoolStopSaving
                : ResUI.DicodePoolStopping;
            Log(status.Text);
        };
        Closing += (_, _) => { _abort?.Cancel(); _stop?.Cancel(); };
        start.Click += async (_, _) =>
        {
            start.IsEnabled = false; cancel.IsEnabled = true; target.IsEnabled = false; rounds.IsEnabled = false; tabs.SelectedIndex = 0;
            using var stop = new CancellationTokenSource(); using var abort = new CancellationTokenSource();
            _stop = stop; _abort = abort;
            var options = new ServerPoolOptions(Convert.ToInt32(target.Value ?? 20), Convert.ToInt32(rounds.Value ?? 3)).Normalize();
            Log(string.Format(ResUI.DicodePoolNewRun, Utils.GetVersion(), options.TargetCount, options.TestRounds));
            try
            {
                await new ServerPoolService().RunAsync((profile, token) => main.ConnectPoolProfileAsync(profile.IndexId, token),
                    new Progress<PoolProgress>(Update), options, stop.Token, abort.Token);
                await main.ProfilesViewModel.RefreshSubscriptions();
                await main.ProfilesViewModel.RefreshServers();
                await Refresh();
            }
            catch (OperationCanceledException) { Update(new(ResUI.DicodePoolStageStopped, ResUI.DicodePoolStoppedKeepPrev)); }
            catch (Exception ex) { Update(new(ResUI.DicodePoolError, ex.Message)); }
            finally {
                _stop = null; _abort = null; _testing = false; start.Content = ResUI.DicodePoolRunAgain;
                start.IsEnabled = true; target.IsEnabled = true; rounds.IsEnabled = true;
                cancel.IsEnabled = false; bar.IsIndeterminate = false;
            }
        };
    }
}
