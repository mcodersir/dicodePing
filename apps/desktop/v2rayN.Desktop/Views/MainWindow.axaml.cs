using Avalonia.Controls.Notifications;
using DialogHostAvalonia;
using v2rayN.Desktop.Base;
using v2rayN.Desktop.Common;
using v2rayN.Desktop.Manager;

namespace v2rayN.Desktop.Views;

public partial class MainWindow : WindowBase<MainWindowViewModel>
{
    private async void OpenEntryHop(object? sender, RoutedEventArgs e)
    {
        if (ViewModel != null) await new EntryHopWindow(ViewModel).ShowDialog(this);
    }

    private async void OpenServerPool(object? sender, RoutedEventArgs e)
    {
        if (ViewModel != null) await new ServerPoolWindow(ViewModel).ShowDialog(this);
    }

    private static Config _config;
    private readonly SingleReplaceableDisposable _layoutBindingsDisposable = new();
    private readonly WindowNotificationManager? _manager;
    private CheckUpdateView? _checkUpdateView;
    private BackupAndRestoreView? _backupAndRestoreView;
    private bool _blCloseByUser = false;
    private bool _dicodePingStartupScheduled;
    private CancellationTokenSource? _startupCts;

    public MainWindow()
    {
        InitializeComponent();
        txtAboutVersion.Text = typeof(MainWindow).Assembly.GetName().Version?.ToString(3) ?? string.Empty;

        // Sidebar navigation: IsCheckedChanged switches pages, Click also re-shows the
        // active page so a misclick can never leave the window unresponsive.
        navHome.IsCheckedChanged += Nav_Checked;
        navHome.Click += Nav_Click;
        navProfiles.IsCheckedChanged += Nav_Checked;
        navProfiles.Click += Nav_Click;
        navProxies.IsCheckedChanged += Nav_Checked;
        navProxies.Click += Nav_Click;
        navSettings.IsCheckedChanged += Nav_Checked;
        navSettings.Click += Nav_Click;
        navReports.IsCheckedChanged += Nav_Checked;
        navReports.Click += Nav_Click;
        navAbout.IsCheckedChanged += Nav_Checked;
        navAbout.Click += Nav_Click;

        // Settings page embeds the sanctions editor; give it its own view model.
        embeddedOptionSetting.Applied += ApplyEmbeddedSettings;
        embeddedDNSSetting.Applied += ApplyEmbeddedSettings;
        embeddedDomainFilterSetting.Applied += ApplyEmbeddedSettings;
        embeddedUpdates.ViewModel = new CheckUpdateViewModel();
        embeddedBackup.ViewModel = new BackupAndRestoreViewModel();
        sanctionsSettingsView.DataContext ??= new SanctionsServicesViewModel();

        menuOptionSetting.Click += (_, _) => OpenSettingsTab(0);
        menuRoutingSetting.Click += (_, _) => OpenSettingsTab(1);
        menuDNSSetting.Click += (_, _) => OpenSettingsTab(3);
        _config = AppManager.Instance.Config;
        _manager = new WindowNotificationManager(TopLevel.GetTopLevel(this)) { MaxItems = 3, Position = NotificationPosition.TopRight };

        KeyDown += MainWindow_KeyDown;
        Closed += (_, _) => _startupCts?.Cancel();
        menuSettingsSetUWP.Click += MenuSettingsSetUWP_Click;
        menuCheckUpdate.Click += MenuCheckUpdate_Click;
        btnNewUpdate.Click += MenuCheckUpdate_Click;
        menuBackupAndRestore.Click += MenuBackupAndRestore_Click;
        menuViewLog.Click += async (_, _) => await DialogHost.Show(new MsgView { DataContext = ViewModel?.MsgViewModel });
        menuClose.Click += MenuClose_Click;

        conTheme.Content ??= new ThemeSettingView();

        this.WhenActivated(disposables =>
        {
            //servers
            this.BindCommand(ViewModel, vm => vm.AddVmessServerCmd, v => v.menuAddVmessServer).DisposeWith(disposables);
            this.BindCommand(ViewModel, vm => vm.AddVlessServerCmd, v => v.menuAddVlessServer).DisposeWith(disposables);
            this.BindCommand(ViewModel, vm => vm.AddShadowsocksServerCmd, v => v.menuAddShadowsocksServer).DisposeWith(disposables);
            this.BindCommand(ViewModel, vm => vm.AddSocksServerCmd, v => v.menuAddSocksServer).DisposeWith(disposables);
            this.BindCommand(ViewModel, vm => vm.AddHttpServerCmd, v => v.menuAddHttpServer).DisposeWith(disposables);
            this.BindCommand(ViewModel, vm => vm.AddTrojanServerCmd, v => v.menuAddTrojanServer).DisposeWith(disposables);
            this.BindCommand(ViewModel, vm => vm.AddHysteria2ServerCmd, v => v.menuAddHysteria2Server).DisposeWith(disposables);
            this.BindCommand(ViewModel, vm => vm.AddTuicServerCmd, v => v.menuAddTuicServer).DisposeWith(disposables);
            this.BindCommand(ViewModel, vm => vm.AddWireguardServerCmd, v => v.menuAddWireguardServer).DisposeWith(disposables);
            this.BindCommand(ViewModel, vm => vm.AddAnytlsServerCmd, v => v.menuAddAnytlsServer).DisposeWith(disposables);
            this.BindCommand(ViewModel, vm => vm.AddNaiveServerCmd, v => v.menuAddNaiveServer).DisposeWith(disposables);
            this.BindCommand(ViewModel, vm => vm.AddCustomServerCmd, v => v.menuAddCustomServer).DisposeWith(disposables);
            this.BindCommand(ViewModel, vm => vm.AddCustomOutboundServerCmd, v => v.menuAddCustomOutboundServer).DisposeWith(disposables);
            this.BindCommand(ViewModel, vm => vm.AddPolicyGroupServerCmd, v => v.menuAddPolicyGroupServer).DisposeWith(disposables);
            this.BindCommand(ViewModel, vm => vm.AddProxyChainServerCmd, v => v.menuAddProxyChainServer).DisposeWith(disposables);
            this.BindCommand(ViewModel, vm => vm.AddServerViaClipboardCmd, v => v.menuAddServerViaClipboard).DisposeWith(disposables);
            this.BindCommand(ViewModel, vm => vm.AddServerViaScanCmd, v => v.menuAddServerViaScan).DisposeWith(disposables);
            this.BindCommand(ViewModel, vm => vm.AddServerViaImageCmd, v => v.menuAddServerViaImage).DisposeWith(disposables);

            //sub
            this.BindCommand(ViewModel, vm => vm.SubUpdateCmd, v => v.menuSubUpdate).DisposeWith(disposables);

            //setting
            this.BindCommand(ViewModel, vm => vm.FullConfigTemplateCmd, v => v.menuFullConfigTemplate).DisposeWith(disposables);
            this.BindCommand(ViewModel, vm => vm.GlobalHotkeySettingCmd, v => v.menuGlobalHotkeySetting).DisposeWith(disposables);
            this.BindCommand(ViewModel, vm => vm.RebootAsAdminCmd, v => v.menuRebootAsAdmin).DisposeWith(disposables);
            this.BindCommand(ViewModel, vm => vm.ClearServerStatisticsCmd, v => v.menuClearServerStatistics).DisposeWith(disposables);
            this.BindCommand(ViewModel, vm => vm.OpenTheFileLocationCmd, v => v.menuOpenTheFileLocation).DisposeWith(disposables);
            this.BindCommand(ViewModel, vm => vm.RegionalPresetDefaultCmd, v => v.menuRegionalPresetsDefault).DisposeWith(disposables);
            this.BindCommand(ViewModel, vm => vm.RegionalPresetRussiaCmd, v => v.menuRegionalPresetsRussia).DisposeWith(disposables);
            this.BindCommand(ViewModel, vm => vm.RegionalPresetIranCmd, v => v.menuRegionalPresetsIran).DisposeWith(disposables);

            this.BindCommand(ViewModel, vm => vm.ReloadCmd, v => v.menuReload).DisposeWith(disposables);
            this.OneWayBind(ViewModel, vm => vm.BlReloadEnabled, v => v.menuReload.IsEnabled).DisposeWith(disposables);
            this.OneWayBind(ViewModel, vm => vm.BlNewUpdate, v => v.btnNewUpdate.IsVisible).DisposeWith(disposables);

            this.OneWayBind(ViewModel, vm => vm.StatusBarViewModel, v => v.contentStatusBarView.Content).DisposeWith(disposables);

            _layoutBindingsDisposable.DisposeWith(disposables);

            this.WhenAnyValue(v => v.ViewModel.MainGirdOrientation)
                .ObserveOn(RxSchedulers.MainThreadScheduler)
                .Subscribe(UpdateLayout)
                .DisposeWith(disposables);

            ViewModel.ReadTextFromClipboardInteraction.RegisterHandler(async interaction =>
            {
                var result = await AvaUtils.GetClipboardData(this);
                interaction.SetOutput(result);
            }).DisposeWith(disposables);

            ViewModel.ScanScreenInteraction.RegisterHandler(async interaction =>
            {
                ShowHideWindow(false);
                await Task.Delay(200);
                var result = QRCodeAvaloniaUtils.CaptureScreen();
                ShowHideWindow(true);
                interaction.SetOutput(result);
            }).DisposeWith(disposables);

            ViewModel.BrowseImageFileInteraction.RegisterHandler(async interaction =>
            {
                var result = await UI.OpenFileDialog(null);
                interaction.SetOutput(result);
            }).DisposeWith(disposables);

            ViewModel.ShowHideWindowInteraction.RegisterHandler(interaction =>
            {
                ShowHideWindow(interaction.Input);
                interaction.SetOutput(RxVoid.Default);
            }).DisposeWith(disposables);

            AppEvents.SendSnackMsgRequested
              .AsObservable()
              .ObserveOn(RxSchedulers.MainThreadScheduler)
              .Subscribe(async content => await DelegateSnackMsg(content))
              .DisposeWith(disposables);

            AppEvents.AppExitRequested
              .AsObservable()
              .ObserveOn(RxSchedulers.MainThreadScheduler)
              .Subscribe(_ => StorageUI())
              .DisposeWith(disposables);

            AppEvents.ShutdownRequested
              .AsObservable()
              .ObserveOn(RxSchedulers.MainThreadScheduler)
              .Subscribe(Shutdown)
              .DisposeWith(disposables);
        });

        if (Utils.IsWindows())
        {
            Title = $"{Utils.GetVersion()} - {(Utils.IsAdministrator() ? ResUI.RunAsAdmin : ResUI.NotRunAsAdmin)}";

            if (!Design.IsDesignMode)
            {
                ThreadPool.RegisterWaitForSingleObject(Program.ProgramStarted, OnProgramStarted, null, -1, false);
                HotkeyManager.Instance.Init(_config, OnHotkeyHandler);
            }
        }
        else
        {
            Title = $"{Utils.GetVersion()}";
            menuAddServerViaScan.IsVisible = false;
        }

        if (_config.UiItem.AutoHideStartup && Utils.IsWindows())
        {
            WindowState = WindowState.Minimized;
        }

    }

    #region Event

    private void Nav_Checked(object? sender, RoutedEventArgs e)
    {
        if (sender is RadioButton { Tag: string page })
        {
            ShowPage(page);
        }
    }

    private void Nav_Click(object? sender, RoutedEventArgs e)
    {
        if (sender is RadioButton { Tag: string page, IsChecked: true })
        {
            ShowPage(page);
        }
    }

    private void OpenTelegramChannel(object? sender, RoutedEventArgs e)
    {
        ProcUtils.ProcessStart("https://t.me/dicodeping");
    }

    private void ShowPage(string page)
    {
        if (_config is not null) _config.UiItem.DesktopPage = page;
        var target = page switch
        {
            "profiles" => pageProfiles,
            "proxies" => pageProxies,
            "settings" => pageSettings,
            "reports" => pageReports,
            "about" => pageAbout,
            _ => pageHome,
        };

        pageHome.IsVisible = target == pageHome;
        pageProfiles.IsVisible = target == pageProfiles;
        pageProxies.IsVisible = target == pageProxies;
        pageSettings.IsVisible = target == pageSettings;
        pageReports.IsVisible = target == pageReports;
        pageAbout.IsVisible = target == pageAbout;

        // Subtle slide-fade so navigation feels alive without being loud.
        target.Opacity = 0;
        target.RenderTransform = Avalonia.Media.Transformation.TransformOperations.Parse("translateY(10px)");
        Dispatcher.UIThread.Post(() =>
        {
            target.Opacity = 1;
            target.RenderTransform = Avalonia.Media.Transformation.TransformOperations.Parse("translateY(0px)");
        }, DispatcherPriority.Loaded);
    }

    private void OnProgramStarted(object state, bool timeout)
    {
        Dispatcher.UIThread.Post(() =>
                ShowHideWindow(true),
            DispatcherPriority.Default);
    }

    private async Task DelegateSnackMsg(string content)
    {
        _manager?.Show(new Avalonia.Controls.Notifications.Notification(null, content, NotificationType.Information));
        await Task.CompletedTask;
    }

    private void OnHotkeyHandler(EGlobalHotkey e)
    {
        switch (e)
        {
            case EGlobalHotkey.ShowForm:
                Dispatcher.UIThread.Post(() => ShowHideWindow(null));
                break;

            case EGlobalHotkey.SystemProxyClear:
            case EGlobalHotkey.SystemProxySet:
            case EGlobalHotkey.SystemProxyUnchanged:
            case EGlobalHotkey.SystemProxyPac:
                AppEvents.SysProxyChangeRequested.Publish((ESysProxyType)((int)e - 1));
                break;
        }
    }

    protected override async void OnClosing(WindowClosingEventArgs e)
    {
        if (_blCloseByUser)
        {
            return;
        }

        Logging.SaveLog("OnClosing -> " + e.CloseReason.ToString());

        switch (e.CloseReason)
        {
            case WindowCloseReason.OwnerWindowClosing or WindowCloseReason.WindowClosing:
                e.Cancel = true;
                ShowHideWindow(false);
                break;

            case WindowCloseReason.ApplicationShutdown or WindowCloseReason.OSShutdown:
                await AppManager.Instance.AppExitAsync(false);
                break;
        }

        base.OnClosing(e);
    }

    private async void MainWindow_KeyDown(object? sender, KeyEventArgs e)
    {
        if (e.KeyModifiers is KeyModifiers.Control or KeyModifiers.Meta)
        {
            switch (e.Key)
            {
                case Key.V:
                    await AddServerViaClipboardAsync();
                    break;

                case Key.S:
                    await ScanScreenTaskAsync();
                    break;
            }
        }
        else
        {
            if (e.Key == Key.F5)
            {
                ViewModel?.Reload();
            }
        }
    }

    private void MenuSettingsSetUWP_Click(object? sender, RoutedEventArgs e)
    {
        ProcUtils.ProcessStart(Utils.GetBinPath("EnableLoopback.exe"));
    }

    public async Task AddServerViaClipboardAsync()
    {
        var clipboardData = await AvaUtils.GetClipboardData(this);
        if (clipboardData.IsNotEmpty() && ViewModel != null)
        {
            await ViewModel.AddServerViaClipboardAsync(clipboardData);
        }
    }

    public async Task ScanScreenTaskAsync()
    {
        ShowHideWindow(false);

        await Task.Delay(200);

        var bytes = QRCodeAvaloniaUtils.CaptureScreen();
        if (bytes != null && ViewModel != null)
        {
            await ViewModel.ScanScreenResult(bytes);
        }

        ShowHideWindow(true);
    }

    private void MenuCheckUpdate_Click(object? sender, RoutedEventArgs e)
    {
        _checkUpdateView ??= new CheckUpdateView();
        _checkUpdateView.ViewModel = ViewModel?.CheckUpdateViewModel;
        DialogHost.Show(_checkUpdateView);

        AppEvents.HasUpdateNotified.Publish(false);
    }

    private void MenuBackupAndRestore_Click(object? sender, RoutedEventArgs e)
    {
        _backupAndRestoreView ??= new BackupAndRestoreView();
        _backupAndRestoreView.ViewModel = ViewModel?.BackupAndRestoreViewModel;
        DialogHost.Show(_backupAndRestoreView);
    }

    private async void MenuClose_Click(object? sender, RoutedEventArgs e)
    {
        try
        {
            if (await UI.ShowYesNo(ResUI.menuExitTips) != ButtonResult.Yes)
            {
                return;
            }

            _blCloseByUser = true;
            StorageUI();

            await AppManager.Instance.AppExitAsync(true);
        }
        catch
        {
            // Ignore
        }
    }

    private void Shutdown(bool obj)
    {
        if (obj is bool b && _blCloseByUser == false)
        {
            _blCloseByUser = b;
        }
        StorageUI();
        if (Application.Current?.ApplicationLifetime is IClassicDesktopStyleApplicationLifetime desktop)
        {
            HotkeyManager.Instance.Dispose();
            desktop.Shutdown();
        }
    }

    #endregion Event

    #region UI

    public void ShowHideWindow(bool? blShow)
    {
        var bl = blShow ??
                    (Utils.IsLinux() || Utils.IsMacOS()
                    ? (!AppManager.Instance.ShowInTaskbar ^ (WindowState == WindowState.Minimized))
                    : !AppManager.Instance.ShowInTaskbar);
        if (bl)
        {
            Show();
            if (WindowState == WindowState.Minimized)
            {
                WindowState = WindowState.Normal;
            }
            Activate();
            Focus();
        }
        else
        {
            if (Utils.IsLinux() && _config.UiItem.Hide2TrayWhenClose == false)
            {
                WindowState = WindowState.Minimized;
                return;
            }

            foreach (var ownedWindow in OwnedWindows)
            {
                ownedWindow.Close();
            }
            Hide();
        }

        AppManager.Instance.ShowInTaskbar = bl;
    }

    protected override void OnLoaded(object? sender, RoutedEventArgs e)
    {
        base.OnLoaded(sender, e);
        if (_config.UiItem.AutoHideStartup)
        {
            ShowHideWindow(false);
        }
        RestoreUI();
        if (!_dicodePingStartupScheduled && ViewModel != null)
        {
            _dicodePingStartupScheduled = true;
            _ = RunDicodePingStartupAsync();
        }
    }

    private async Task ShowTelegramChannelPromptAsync()
    {
        try
        {
            var promptFile = Utils.GetConfigPath("dicodeping-channel-prompt.txt");
            var count = File.Exists(promptFile) && int.TryParse(await File.ReadAllTextAsync(promptFile), out var saved)
                ? saved : 0;
            if (count >= 3)
            {
                return;
            }
            await File.WriteAllTextAsync(promptFile, (count + 1).ToString());
            if (await UI.ShowYesNo(ResUI.DicodeJoinTelegramPrompt) == ButtonResult.Yes)
            {
                ProcUtils.ProcessStart("https://t.me/dicodeping");
            }
        }
        catch
        {
            // A non-essential welcome prompt must never prevent startup.
        }
    }

    private void SkipPreparation(object? sender, RoutedEventArgs e) => _startupCts?.Cancel();

    private async Task RunDicodePingStartupAsync()
    {
        using var cts = new CancellationTokenSource(TimeSpan.FromMinutes(4));
        _startupCts = cts;
        try
        {
            await ViewModel.ProfilesViewModel.RefreshSubscriptions();
            await ViewModel.ProfilesViewModel.RefreshServersBiz();
            var primary = (await AppManager.Instance.SubItems())?.FirstOrDefault(item =>
                string.Equals(item.Url, DicodePingBootstrap.DefaultSubscriptionUrl, StringComparison.OrdinalIgnoreCase));
            if (!DicodePingBootstrap.ShouldPrepare(_config, primary)) return;
            ViewModel.IsPreparing = true;
            ViewModel.PreparationStatus = ResUI.DicodeRefreshRunning;
            await Task.Run(() => SubscriptionHandler.UpdateProcess(_config, primary!.Id, false,
                (_, message) => { Dispatcher.UIThread.Post(() => ViewModel.PreparationStatus = message); return Task.CompletedTask; }, cts.Token));
            cts.Token.ThrowIfCancellationRequested();
            await ViewModel.ProfilesViewModel.RefreshSubscriptions();
            await ViewModel.ProfilesViewModel.RefreshServersBiz();
            var profiles = await AppManager.Instance.ProfileItems(primary!.Id) ?? [];
            if (profiles.Count == 0) return;
            ViewModel.PreparationStatus = ResUI.DicodeProbeLatency;
            await ViewModel.ProfilesViewModel.ServerSpeedtest(ESpeedActionType.FastRealping, profiles, cts.Token);
            cts.Token.ThrowIfCancellationRequested();
            await ConfigHandler.SortServers(_config, primary.Id, nameof(EServerColName.DelayVal), true);
            var delays = (await ProfileExManager.Instance.GetProfileExs()).ToDictionary(x => x.IndexId, x => x.Delay);
            var reachable = profiles.Where(x => delays.GetValueOrDefault(x.IndexId) > 0).ToList();
            if (reachable.Count > 0)
            {
                ViewModel.PreparationStatus = ResUI.DicodeProbeLocation;
                await ViewModel.ProfilesViewModel.ServerSpeedtest(ESpeedActionType.Location, reachable, cts.Token);
            }
            await ViewModel.ProfilesViewModel.RefreshServersBiz();
            var best = reachable.OrderBy(x => delays.GetValueOrDefault(x.IndexId)).FirstOrDefault();
            if (best is not null && !CoreManager.Instance.IsRunning)
                await ViewModel.ProfilesViewModel.SetDefaultServer(best.IndexId);
            await ViewModel.StatusBarViewModel.RefreshServersBiz();
        }
        catch (OperationCanceledException) { await ViewModel.ProfilesViewModel.StopDiagnosticsAsync(); }
        catch (Exception ex) { Logging.SaveLog("DicodePingStartup", ex); }
        finally
        {
            ViewModel.IsPreparing = false;
            _startupCts = null;
        }
    }

    private void RestoreUI()
    {
        ShowPage(_config.UiItem.DesktopPage);
    }

    private void StorageUI()
    {
        ConfigHandler.SaveWindowSizeItem(_config, GetType().Name, Width, Height);
        _ = ConfigHandler.SaveConfig(_config);

    }

    private void UpdateLayout(EGirdOrientation orientation)
    {
        var currentLayoutDisposables = new MultipleDisposable();
        _layoutBindingsDisposable.Create(currentLayoutDisposables);

        this.OneWayBind(ViewModel, vm => vm.ProfilesViewModel, v => v.tabProfiles.Content).DisposeWith(currentLayoutDisposables);
        this.OneWayBind(ViewModel, vm => vm.ClashProxiesViewModel, v => v.tabProxies.Content).DisposeWith(currentLayoutDisposables);
        this.OneWayBind(ViewModel, vm => vm.MsgViewModel, v => v.tabReports.Content).DisposeWith(currentLayoutDisposables);
    }

    private void MenuItem_Click(object? sender, RoutedEventArgs e)
    {
        if (sender is MenuItem item)
        {
            ProcUtils.ProcessStart(item.Tag?.ToString());
        }
    }

    #endregion UI
    private void OpenSettingsTab(int index)
    {
        navSettings.IsChecked = true;
        settingsTabs.SelectedIndex = index;
    }

    private async void ApplyEmbeddedSettings(object? sender, EventArgs args)
    {
        try { if (ViewModel != null) await ViewModel.Reload(); }
        catch (Exception error) { Logging.SaveLog("ApplyEmbeddedSettings", error); NoticeManager.Instance.Enqueue(error.Message); }
    }
}
