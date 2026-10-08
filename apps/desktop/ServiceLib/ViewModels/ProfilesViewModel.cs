namespace ServiceLib.ViewModels;

public partial class ProfilesViewModel : MyReactiveObject
{
    public Interaction<string, bool> ShowYesNoInteraction { get; } = new();
    public Interaction<ProfileItem, bool> SaveFileDialogInteraction { get; } = new();
    public Interaction<string, RxVoid> SetClipboardDataInteraction { get; } = new();
    public Interaction<RxVoid, RxVoid> ProfilesFocusInteraction { get; } = new();
    public Interaction<string, RxVoid> ShareServerInteraction { get; } = new();
    public Interaction<RxVoid, RxVoid> DispatcherRefreshServersBizInteraction { get; } = new();
    public Interaction<RxVoid, RxVoid> AdjustMainLvColWidthInteraction { get; } = new();

    public EventChannel<RxVoid> ReloadRequested { get; } = new();
    public EventChannel<RxVoid> ConnectionStartRequested { get; } = new();
    public EventChannel<RxVoid> ConnectionStopRequested { get; } = new();
    public EventChannel<RxVoid> RefreshServersRequested { get; } = new();

    #region private prop

    private string _serverFilter = string.Empty;
    private readonly Dictionary<string, bool> _dicHeaderSort = new();
    private readonly ConcurrentDictionary<string, ProfileItemModel> _profileLookup = new();
    private readonly ConcurrentDictionary<ESpeedActionType, SpeedtestService> _probeServices = new();
    private string? _pendingSelectIndexId;
    private readonly Timer _connectionStateTimer;
    private readonly ConcurrentDictionary<ESpeedActionType, SemaphoreSlim> _probeLocks = new();
    private CancellationTokenSource? _securityCts;

    #endregion private prop

    #region ObservableCollection

    public BulkObservableCollection<ProfileItemModel> ProfileItems { get; } = [];

    public BulkObservableCollection<SubItem> SubItems { get; } = [];
    public ObservableCollection<ProbeRunModel> ProbeRuns { get; } = [];
    [Reactive] public partial bool IsRefreshing { get; set; }
    private readonly Dictionary<ESpeedActionType, ProbeRunModel> _probeRuns = new();

    [Reactive]
    public partial ProfileItemModel SelectedProfile { get; set; }

    public IList<ProfileItemModel> SelectedProfiles { get; set; }

    [Reactive]
    public partial SubItem SelectedSub { get; set; }

    [Reactive]
    public partial SubItem SelectedMoveToGroup { get; set; }

    [Reactive]
    public partial string ServerFilter { get; set; }

    [Reactive]
    public partial bool IsConnected { get; set; }

    [Reactive]
    public partial bool HasProfiles { get; set; }

    [Reactive]
    public partial string ConnectionStatusText { get; set; }

    #endregion ObservableCollection

    #region Menu

    //servers delete
    public ReactiveCommand<RxVoid, RxVoid> EditServerCmd { get; }

    public ReactiveCommand<RxVoid, RxVoid> RemoveServerCmd { get; }
    public ReactiveCommand<RxVoid, RxVoid> RemoveDuplicateServerCmd { get; }
    public ReactiveCommand<RxVoid, RxVoid> CopyServerCmd { get; }
    public ReactiveCommand<RxVoid, RxVoid> SetDefaultServerCmd { get; }
    public ReactiveCommand<RxVoid, RxVoid> ShareServerCmd { get; }
    public ReactiveCommand<RxVoid, RxVoid> GenGroupAllServerCmd { get; }
    public ReactiveCommand<RxVoid, RxVoid> GenGroupRegionServerCmd { get; }

    //servers move
    public ReactiveCommand<RxVoid, RxVoid> MoveTopCmd { get; }

    public ReactiveCommand<RxVoid, RxVoid> MoveUpCmd { get; }
    public ReactiveCommand<RxVoid, RxVoid> MoveDownCmd { get; }
    public ReactiveCommand<RxVoid, RxVoid> MoveBottomCmd { get; }
    public ReactiveCommand<SubItem, RxVoid> MoveToGroupCmd { get; }

    //servers ping
    public ReactiveCommand<RxVoid, RxVoid> MixedTestServerCmd { get; }

    public ReactiveCommand<RxVoid, RxVoid> TcpingServerCmd { get; }
    public ReactiveCommand<RxVoid, RxVoid> RealPingServerCmd { get; }
    public ReactiveCommand<RxVoid, RxVoid> LocationTestCmd { get; }
    public ReactiveCommand<RxVoid, RxVoid> SecurityTestCmd { get; }
    public ReactiveCommand<RxVoid, RxVoid> SanctionsTestCmd { get; }
    public ReactiveCommand<RxVoid, RxVoid> UdpTestServerCmd { get; }
    public ReactiveCommand<RxVoid, RxVoid> SpeedServerCmd { get; }
    public ReactiveCommand<RxVoid, RxVoid> SortServerResultCmd { get; }
    public ReactiveCommand<RxVoid, RxVoid> RemoveInvalidServerResultCmd { get; }
    public ReactiveCommand<RxVoid, RxVoid> FastRealPingCmd { get; }
    public ReactiveCommand<RxVoid, RxVoid> ConnectSelectedCmd { get; }
    public ReactiveCommand<RxVoid, RxVoid> ConnectBestCmd { get; }

    //servers export
    public ReactiveCommand<RxVoid, RxVoid> Export2ClientConfigCmd { get; }

    public ReactiveCommand<RxVoid, RxVoid> Export2ClientConfigClipboardCmd { get; }
    public ReactiveCommand<RxVoid, RxVoid> Export2ShareUrlCmd { get; }
    public ReactiveCommand<RxVoid, RxVoid> Export2ShareUrlBase64Cmd { get; }
    public ReactiveCommand<RxVoid, RxVoid> Export2InnerUriCmd { get; }

    public ReactiveCommand<RxVoid, RxVoid> AddSubCmd { get; }
    public ReactiveCommand<RxVoid, RxVoid> EditSubCmd { get; }
    public ReactiveCommand<RxVoid, RxVoid> DeleteSubCmd { get; }

    #endregion Menu

    #region Init

    public ProfilesViewModel()
    {
        _config = AppManager.Instance.Config;
        ConnectionStatusText = ResUI.DicodeTunConnect;

        #region WhenAnyValue && ReactiveCommand

        var canEditRemove = this.WhenAnyValue(
           x => x.SelectedProfile,
           selectedSource => selectedSource != null && !selectedSource.IndexId.IsNullOrEmpty());

        this.WhenAnyValue(x => x.SelectedSub)
            .Where(y => y != null && !y.Remarks.IsNullOrEmpty() && _config.SubIndexId != y.Id)
            .SubscribeAsync(async _ => await SubSelectedChangedAsync());
        this.WhenAnyValue(x => x.SelectedMoveToGroup)
            .Where(y => y != null && !y.Remarks.IsNullOrEmpty())
            .SubscribeAsync(async _ => await MoveToGroup());

        this.WhenAnyValue(x => x.ServerFilter)
            .Throttle(TimeSpan.FromMilliseconds(250), RxSchedulers.MainThreadScheduler)
            .DistinctUntilChanged()
            .Where(y => y != null && _serverFilter != y)
            .SubscribeAsync(async _ => await ServerFilterChanged());

        _connectionStateTimer = new Timer(_ =>
        {
            RxSchedulers.MainThreadScheduler.Schedule(() =>
            {
                IsConnected = CoreManager.Instance.IsRunning;
                ConnectionStatusText = IsConnected ? ResUI.DicodeTunConnected : ResUI.DicodeTunConnect;
            });
        }, null, TimeSpan.Zero, TimeSpan.FromMilliseconds(500));

        //servers delete
        EditServerCmd = ReactiveCommand.CreateFromTask(async () =>
        {
            await EditServerAsync();
        }, canEditRemove);
        RemoveServerCmd = ReactiveCommand.CreateFromTask(async () =>
        {
            await RemoveServerAsync();
        }, canEditRemove);
        RemoveDuplicateServerCmd = ReactiveCommand.CreateFromTask(async () =>
        {
            await RemoveDuplicateServer();
        });
        CopyServerCmd = ReactiveCommand.CreateFromTask(async () =>
        {
            await CopyServer();
        }, canEditRemove);
        SetDefaultServerCmd = ReactiveCommand.CreateFromTask(async () =>
        {
            await SetDefaultServer();
        }, canEditRemove);
        ShareServerCmd = ReactiveCommand.CreateFromTask(async () =>
        {
            await ShareServerAsync();
        }, canEditRemove);
        GenGroupAllServerCmd = ReactiveCommand.CreateFromTask(async () =>
        {
            await GenGroupAllServer();
        }, canEditRemove);
        GenGroupRegionServerCmd = ReactiveCommand.CreateFromTask(async () =>
        {
            await GenGroupRegionServer();
        }, canEditRemove);

        //servers move
        MoveTopCmd = ReactiveCommand.CreateFromTask(async () =>
        {
            await MoveServer(EMove.Top);
        }, canEditRemove);
        MoveUpCmd = ReactiveCommand.CreateFromTask(async () =>
        {
            await MoveServer(EMove.Up);
        }, canEditRemove);
        MoveDownCmd = ReactiveCommand.CreateFromTask(async () =>
        {
            await MoveServer(EMove.Down);
        }, canEditRemove);
        MoveBottomCmd = ReactiveCommand.CreateFromTask(async () =>
        {
            await MoveServer(EMove.Bottom);
        }, canEditRemove);
        MoveToGroupCmd = ReactiveCommand.CreateFromTask<SubItem>(async sub =>
        {
            SelectedMoveToGroup = sub;
        });

        //servers ping
        FastRealPingCmd = ReactiveCommand.CreateFromTask(async () =>
        {
            await ServerSpeedtest(ESpeedActionType.FastRealping);
        });
        ConnectSelectedCmd = ReactiveCommand.CreateFromTask(async () =>
        {
            await ConnectSelectedAsync();
        });
        ConnectBestCmd = ReactiveCommand.CreateFromTask(async () =>
        {
            await ConnectBestAsync();
        });
        MixedTestServerCmd = ReactiveCommand.CreateFromTask(async () =>
        {
            await ServerSpeedtest(ESpeedActionType.Speedtest);
        });
        TcpingServerCmd = ReactiveCommand.CreateFromTask(async () =>
        {
            await ServerSpeedtest(ESpeedActionType.Tcping);
        }, canEditRemove);
        RealPingServerCmd = ReactiveCommand.CreateFromTask(async () =>
        {
            await ServerSpeedtest(ESpeedActionType.Realping);
        }, canEditRemove);
        // Location beta probes every visible profile through its own temporary
        // proxy and only updates the location field, never the saved latency.
        LocationTestCmd = ReactiveCommand.CreateFromTask(async () =>
        {
            await ServerSpeedtest(ESpeedActionType.Location);
        });
        SecurityTestCmd = ReactiveCommand.CreateFromTask(async () =>
        {
            using var cancellation = new CancellationTokenSource();
            _securityCts = cancellation;
            var rows = ProfileItems.ToList();
            foreach (var previous in ProbeRuns.Where(x => x.Name == ResUI.DicodeProbeSecurity && !x.IsRunning).ToList()) ProbeRuns.Remove(previous);
            var run = new ProbeRunModel { Name = ResUI.DicodeProbeSecurity, Total = rows.Count };
            ProbeRuns.Add(run); run.UpdateSummary(ResUI.DicodeProbeRunning);
            try
            {
                var profiles = await AppManager.Instance.GetProfileItemsByIndexIdsAsMap(rows.Select(x => x.IndexId).ToList());
                foreach (var model in rows)
                {
                    cancellation.Token.ThrowIfCancellationRequested();
                    model.IsSecurityTesting = true;
                    try
                    {
                        if (profiles.TryGetValue(model.IndexId, out var profile))
                            model.SecurityInfo = await Task.Run(() => ConfigurationSecurityAudit.Describe(profile));
                        run.Complete(model.IndexId);
                    }
                    finally { model.IsSecurityTesting = false; }
                }
                run.UpdateSummary(ResUI.SpeedtestingCompleted);
            }
            catch (OperationCanceledException) { run.UpdateSummary(ResUI.SpeedtestingStop); }
            finally { run.IsRunning = false; _securityCts = null; }
        });
        SanctionsTestCmd = ReactiveCommand.CreateFromTask(async () =>
        {
            await ServerSpeedtest(ESpeedActionType.Sanctions);
        });
        UdpTestServerCmd = ReactiveCommand.CreateFromTask(async () =>
        {
            await ServerSpeedtest(ESpeedActionType.UdpTest);
        }, canEditRemove);
        SpeedServerCmd = ReactiveCommand.CreateFromTask(async () =>
        {
            await ServerSpeedtest(ESpeedActionType.Speedtest);
        }, canEditRemove);
        SortServerResultCmd = ReactiveCommand.CreateFromTask(async () =>
        {
            await SortServer(nameof(EServerColName.DelayVal));
        });
        RemoveInvalidServerResultCmd = ReactiveCommand.CreateFromTask(async () =>
        {
            await RemoveInvalidServerResult();
        });
        //servers export
        Export2ClientConfigCmd = ReactiveCommand.CreateFromTask(async () =>
        {
            await Export2ClientConfigAsync(false);
        }, canEditRemove);
        Export2ClientConfigClipboardCmd = ReactiveCommand.CreateFromTask(async () =>
        {
            await Export2ClientConfigAsync(true);
        }, canEditRemove);
        Export2ShareUrlCmd = ReactiveCommand.CreateFromTask(async () =>
        {
            await Export2ShareUrlAsync(false);
        }, canEditRemove);
        Export2ShareUrlBase64Cmd = ReactiveCommand.CreateFromTask(async () =>
        {
            await Export2ShareUrlAsync(true);
        }, canEditRemove);
        Export2InnerUriCmd = ReactiveCommand.CreateFromTask(async () =>
        {
            await Export2InnerUrlAsync();
        }, canEditRemove);

        //Subscription
        AddSubCmd = ReactiveCommand.CreateFromTask(async () =>
        {
            await EditSubAsync(true);
        });
        EditSubCmd = ReactiveCommand.CreateFromTask(async () =>
        {
            await EditSubAsync(false);
        });
        DeleteSubCmd = ReactiveCommand.CreateFromTask(async () =>
        {
            await DeleteSubAsync();
        });

        #endregion WhenAnyValue && ReactiveCommand

        #region AppEvents

        AppEvents.DispatcherStatisticsRequested
            .AsObservable()
            .ObserveOn(RxSchedulers.MainThreadScheduler)
            .SubscribeAsync(async result => await UpdateStatistics(result));

        #endregion AppEvents

        _ = Init();
    }

    private async Task Init()
    {
        SelectedProfile = new();
        SelectedSub = new();
        SelectedMoveToGroup = new();

        await RefreshSubscriptions();
        //await RefreshServers();
    }

    #endregion Init

    #region Actions

    private void Reload()
    {
        ReloadRequested.Publish();
    }

    public Task SetSpeedTestResult(SpeedTestResult result) => ApplyProbeResult(result, ESpeedActionType.Mixedtest);

    private Task ApplyProbeResult(SpeedTestResult result, ESpeedActionType action)
    {
        if (result.IndexId.IsNullOrEmpty())
        {
            if (result.Delay == ResUI.SpeedtestingCompleted)
            {
                foreach (var row in ProfileItems) SetMetricBusy(row, action, false);
            }
            else if (result.Delay.IsNotEmpty()) NoticeManager.Instance.SendMessageEx(result.Delay);
            return Task.CompletedTask;
        }
        var item = _profileLookup.GetValueOrDefault(result.IndexId) ?? ProfileItems.FirstOrDefault(x => x.IndexId == result.IndexId);
        if (item is null) return Task.CompletedTask;
        static bool IsPending(string? value) => value == ResUI.Speedtesting || value == ResUI.DicodeChecking;
        if (result.Delay.IsNotEmpty() && action is not ESpeedActionType.Speedtest && !IsPending(result.Delay))
        {
            item.Delay = int.TryParse(result.Delay, out var delay) ? delay : -1;
            item.DelayVal = item.Delay > 0 ? result.Delay! : "—";
            item.IsLatencyTesting = false;
        }
        if (result.Speed.IsNotEmpty() && !IsPending(result.Speed))
        {
            item.SpeedVal = result.Speed!;
            if (decimal.TryParse(result.Speed, out var speed)) item.Speed = speed;
            item.IsSpeedTesting = false;
        }
        if (result.IpInfo.IsNotEmpty() && !IsPending(result.IpInfo))
        {
            item.IpInfo = result.IpInfo!;
            item.IsLocationTesting = false;
        }
        if (result.SanctionsInfo.IsNotEmpty() && !IsPending(result.SanctionsInfo))
        {
            item.SanctionsInfo = result.SanctionsInfo!;
            item.IsSanctionsTesting = false;
        }
        return Task.CompletedTask;
    }

    private static void SetMetricBusy(ProfileItemModel item, ESpeedActionType action, bool busy)
    {
        switch (action)
        {
            case ESpeedActionType.Location: item.IsLocationTesting = busy; break;
            case ESpeedActionType.Sanctions: item.IsSanctionsTesting = busy; break;
            case ESpeedActionType.Speedtest: item.IsSpeedTesting = busy; break;
            case ESpeedActionType.Mixedtest: item.IsSpeedTesting = busy; item.IsLatencyTesting = busy; break;
            default: item.IsLatencyTesting = busy; break;
        }
        item.IsTesting = item.IsLatencyTesting || item.IsSpeedTesting || item.IsLocationTesting || item.IsSanctionsTesting;
    }

    public async Task UpdateStatistics(ServerSpeedItem update)
    {
        if (!_config.GuiItem.EnableStatistics
            || (update.ProxyUp + update.ProxyDown) <= 0
            || DateTime.Now.Second % 3 != 0)
        {
            return;
        }

        try
        {
            var item = ProfileItems.FirstOrDefault(it => it.IndexId == update.IndexId);
            if (item != null)
            {
                item.TodayDown = Utils.HumanFy(update.TodayDown);
                item.TodayUp = Utils.HumanFy(update.TodayUp);
                item.TotalDown = Utils.HumanFy(update.TotalDown);
                item.TotalUp = Utils.HumanFy(update.TotalUp);
            }
        }
        catch
        {
        }
        await Task.CompletedTask;
    }

    #endregion Actions

    #region Servers && Groups

    private async Task SubSelectedChangedAsync()
    {
        _config.SubIndexId = SelectedSub?.Id;

        await RefreshServers();

        await ProfilesFocusInteraction.HandleSafe(RxVoid.Default);
    }

    private async Task ServerFilterChanged()
    {
        _serverFilter = ServerFilter;
        if (_serverFilter.IsNullOrEmpty())
        {
            await RefreshServers();
        }
    }

    public async Task RefreshServers()
    {
        RefreshServersRequested.Publish();

        // await Task.Delay(200);

        await Task.CompletedTask;
    }

    public async Task RefreshServersBiz()
    {
        var lstModel = await GetProfileItemsEx(_config.SubIndexId, _serverFilter);

        // A background subscription refresh may overlap a test. Prefer the
        // currently visible valid measurements if the DB snapshot is older.
        // Subscription sources can temporarily contain the same profile id more
        // than once. Never let a UI refresh turn that data issue into a crash.
        var current = ProfileItems
            .Where(item => item.IndexId.IsNotEmpty())
            .GroupBy(item => item.IndexId)
            .ToDictionary(group => group.Key, group => group.First());
        foreach (var next in lstModel ?? [])
        {
            if (!current.TryGetValue(next.IndexId, out var previous))
            {
                continue;
            }
            next.SecurityInfo = previous.SecurityInfo;
            next.IsLatencyTesting = previous.IsLatencyTesting; next.IsSpeedTesting = previous.IsSpeedTesting;
            next.IsLocationTesting = previous.IsLocationTesting; next.IsSanctionsTesting = previous.IsSanctionsTesting;
            next.IsSecurityTesting = previous.IsSecurityTesting;
            if (next.IpInfo.IsNullOrEmpty() && previous.IpInfo.IsNotEmpty())
            {
                next.IpInfo = previous.IpInfo;
            }
            if (next.SanctionsInfo.IsNullOrEmpty() && previous.SanctionsInfo.IsNotEmpty())
            {
                next.SanctionsInfo = previous.SanctionsInfo;
            }
        }
        for (var row = 0; row < (lstModel?.Count ?? 0); row++)
            lstModel![row].RowNumber = row + 1;
        ProfileItems.ReplaceAll(lstModel ?? []);
        HasProfiles = ProfileItems.Count > 0;
        _profileLookup.Clear();
        foreach (var item in ProfileItems) _profileLookup[item.IndexId] = item;
        if (lstModel?.Count > 0)
        {
            ProfileItemModel? selected = null;
            if (!_pendingSelectIndexId.IsNullOrEmpty())
            {
                selected = lstModel.FirstOrDefault(t => t.IndexId == _pendingSelectIndexId);
                _pendingSelectIndexId = null;
            }
            selected ??= lstModel.FirstOrDefault(t => t.IndexId == _config.IndexId);
            SelectedProfile = selected ?? lstModel.First();
        }

        await DispatcherRefreshServersBizInteraction.HandleSafe(RxVoid.Default);
    }

    public async Task RefreshSubscriptions()
    {
        var subItems = await AppManager.Instance.SubItems();
        subItems.Insert(0, new SubItem { Remarks = ResUI.AllGroupServers });

        SubItems.ReplaceRange(subItems);

        SelectedSub = (_config.SubIndexId.IsNotEmpty()
                        ? subItems.FirstOrDefault(t => t.Id == _config.SubIndexId)
                        : null) ?? subItems.FirstOrDefault();
    }

    public async Task AdjustMainLvColWidth()
    {
        await AdjustMainLvColWidthInteraction.HandleSafe(RxVoid.Default);
    }

    private async Task<List<ProfileItemModel>?> GetProfileItemsEx(string subid, string filter)
    {
        var lstModel = await AppManager.Instance.ProfileModels(_config.SubIndexId, filter);

        // Merely refreshing or filtering the grid must never change the user's
        // manually selected server. Selection recovery is handled explicitly
        // only after a removed subscription profile has been replaced.

        var lstServerStat = (_config.GuiItem.EnableStatistics ? StatisticsManager.Instance.ServerStat : null) ?? [];
        var lstProfileExs = await ProfileExManager.Instance.GetProfileExs();
        var auditMap = await AppManager.Instance.GetProfileItemsByIndexIdsAsMap(lstModel.Select(x => x.IndexId).ToList());
        var subscriptionMap = (await AppManager.Instance.SubItems()).DistinctBy(x => x.Id).ToDictionary(x => x.Id);
        lstModel = (from t in lstModel
                    join t2 in lstServerStat on t.IndexId equals t2.IndexId into t2b
                    from t22 in t2b.DefaultIfEmpty()
                    join t3 in lstProfileExs on t.IndexId equals t3.IndexId into t3b
                    from t33 in t3b.DefaultIfEmpty()
                    select new ProfileItemModel
                    {
                        IndexId = t.IndexId,
                        ConfigType = t.ConfigType,
                        Remarks = t.Remarks,
                        Address = t.Address,
                        Port = t.Port,
                        //Security = t.Security,
                        Network = t.Network,
                        StreamSecurity = t.StreamSecurity,
                        Subid = t.Subid,
                        SubRemarks = t.SubRemarks,
                        SubscriptionUsage = FormatSubscriptionUsage(subscriptionMap.GetValueOrDefault(t.Subid)),
                        IsActive = t.IndexId == _config.IndexId,
                        Sort = t33?.Sort ?? 0,
                        Delay = t33?.Delay ?? 0,
                        Speed = t33?.Speed ?? 0,
                        DelayVal = t33?.Delay != 0 ? $"{t33?.Delay}" : string.Empty,
                        SpeedVal = t33?.Speed > 0 ? $"{t33?.Speed}" : t33?.Message ?? string.Empty,
                        IpInfo = t33?.IpInfo ?? string.Empty,
                        SanctionsInfo = t33?.SanctionsInfo ?? string.Empty,
                        SecurityInfo = auditMap.TryGetValue(t.IndexId, out var audited) ? ConfigurationSecurityAudit.Describe(audited) : "—",
                        TodayDown = t22 == null ? "" : Utils.HumanFy(t22.TodayDown),
                        TodayUp = t22 == null ? "" : Utils.HumanFy(t22.TodayUp),
                        TotalDown = t22 == null ? "" : Utils.HumanFy(t22.TotalDown),
                        TotalUp = t22 == null ? "" : Utils.HumanFy(t22.TotalUp)
                    }).OrderBy(t => t.Sort)
                      .ToList();

        return lstModel;
    }

    private static string FormatSubscriptionUsage(SubItem? sub)
    {
        if (sub is null || sub.TotalBytes <= 0) return string.Empty;
        var used = Math.Max(0, sub.UploadBytes + sub.DownloadBytes);
        return $"{Utils.HumanFy(used / 1024)} / {Utils.HumanFy(sub.TotalBytes / 1024)}";
    }

    #endregion Servers && Groups

    #region Add Servers

    private async Task<List<ProfileItem>?> GetProfileItems(bool latest)
    {
        var lstSelected = new List<ProfileItem>();
        if (SelectedProfiles == null || SelectedProfiles.Count <= 0)
        {
            return null;
        }

        var orderProfiles = SelectedProfiles?.OrderBy(t => t.Sort);
        if (latest)
        {
            lstSelected.AddRange(await AppManager.Instance.GetProfileItemsOrderedByIndexIds(orderProfiles.Select(sp => sp?.IndexId)));
        }
        else
        {
            lstSelected = JsonUtils.Deserialize<List<ProfileItem>>(JsonUtils.Serialize(orderProfiles));
        }

        return lstSelected;
    }

    public async Task EditServerAsync()
    {
        if (string.IsNullOrEmpty(SelectedProfile?.IndexId))
        {
            return;
        }
        var item = await AppManager.Instance.GetProfileItem(SelectedProfile.IndexId);
        if (item is null)
        {
            NoticeManager.Instance.Enqueue(ResUI.PleaseSelectServer);
            return;
        }
        var eConfigType = item.ConfigType;

        bool? ret = false;
        if (eConfigType is EConfigType.Custom or EConfigType.Outbound)
        {
            var addServer2ViewModel = new AddServer2ViewModel(item);
            ret = await AppManager.Instance.WindowDialog.ShowDialogAsync(addServer2ViewModel);
        }
        else if (eConfigType.IsGroupType())
        {
            var addGroupServerViewModel = new AddGroupServerViewModel(item);
            ret = await AppManager.Instance.WindowDialog.ShowDialogAsync(addGroupServerViewModel);
        }
        else
        {
            var addServerViewModel = new AddServerViewModel(item);
            ret = await AppManager.Instance.WindowDialog.ShowDialogAsync(addServerViewModel);
        }
        if (ret == true)
        {
            await RefreshServers();
            if (item.IndexId == _config.IndexId)
            {
                Reload();
            }
        }
    }

    public async Task RemoveServerAsync()
    {
        var lstSelected = await GetProfileItems(true);
        if (lstSelected == null)
        {
            return;
        }
        if (await ShowYesNoInteraction.HandleSafe(ResUI.RemoveServer) == false)
        {
            return;
        }
        var exists = lstSelected.Exists(t => t.IndexId == _config.IndexId);

        await ConfigHandler.RemoveServers(_config, lstSelected);
        NoticeManager.Instance.Enqueue(ResUI.OperationSuccess);
        if (lstSelected.Count == ProfileItems.Count)
        {
            ProfileItems.Clear();
        }
        await RefreshServers();
        if (exists)
        {
            Reload();
        }
    }

    private async Task RemoveDuplicateServer()
    {
        if (await ShowYesNoInteraction.HandleSafe(ResUI.RemoveServer) == false)
        {
            return;
        }

        var tuple = await ConfigHandler.DedupServerList(_config, _config.SubIndexId);
        if (tuple.Item1 > 0 || tuple.Item2 > 0)
        {
            await RefreshServers();
            Reload();
        }
        NoticeManager.Instance.Enqueue(string.Format(ResUI.RemoveDuplicateServerResult, tuple.Item1, tuple.Item2));
    }

    private async Task CopyServer()
    {
        var lstSelected = await GetProfileItems(false);
        if (lstSelected == null)
        {
            return;
        }
        if (await ConfigHandler.CopyServer(_config, lstSelected) == 0)
        {
            await RefreshServers();
            NoticeManager.Instance.Enqueue(ResUI.OperationSuccess);
        }
    }

    public async Task SetDefaultServer()
    {
        if (string.IsNullOrEmpty(SelectedProfile?.IndexId))
        {
            return;
        }
        await SetDefaultServer(SelectedProfile.IndexId);
    }

    public async Task SetDefaultServer(string? indexId)
    {
        if (indexId.IsNullOrEmpty())
        {
            return;
        }
        if (indexId == _config.IndexId)
        {
            foreach (var profile in ProfileItems)
            {
                profile.IsActive = profile.IndexId == indexId;
            }
            return;
        }
        var item = await AppManager.Instance.GetProfileItem(indexId);
        if (item is null)
        {
            NoticeManager.Instance.Enqueue(ResUI.PleaseSelectServer);
            return;
        }

        var restartRunningConnection = CoreManager.Instance.IsRunning;
        if (await ConfigHandler.SetDefaultServerIndex(_config, indexId) == 0)
        {
            foreach (var profile in ProfileItems)
            {
                profile.IsActive = profile.IndexId == indexId;
            }
            SelectedProfile = ProfileItems.FirstOrDefault(profile => profile.IndexId == indexId) ?? SelectedProfile;
            await RefreshServers();
            // Selecting a row while disconnected must never start the tunnel.  Only
            // replace the active route when the user was already connected.
            if (restartRunningConnection)
            {
                Reload();
            }
        }
    }

    public async Task ConnectSelectedAsync()
    {
        if (CoreManager.Instance.IsRunning)
        {
            ConnectionStopRequested.Publish();
            return;
        }

        if (SelectedProfile is null || SelectedProfile.IndexId.IsNullOrEmpty())
        {
            NoticeManager.Instance.Enqueue(ResUI.PleaseSelectServer);
            return;
        }

        _config.TunModeItem.EnableTun = true;
        await ConfigHandler.SaveConfig(_config);
        if (SelectedProfile.IndexId == _config.IndexId)
        {
            NoticeManager.Instance.Enqueue(ResUI.DicodeConnectingSelected);
        }
        else
        {
            NoticeManager.Instance.Enqueue(ResUI.DicodeConnectingSelected);
            await SetDefaultServer(SelectedProfile.IndexId);
        }
        ConnectionStartRequested.Publish();
        await WaitForConnectionAsync();
    }

    public async Task ConnectBestAsync()
    {
        if (CoreManager.Instance.IsRunning)
        {
            ConnectionStopRequested.Publish();
            return;
        }

        // The first smart-connect action must be useful on a fresh install too.  Wait for
        // real-path measurements before selecting when no usable result has been recorded.
        if (!ProfileItems.Any(item => item.Delay > 0))
        {
            NoticeManager.Instance.Enqueue(ResUI.DicodeSmartTesting);
            await ServerSpeedtest(ESpeedActionType.FastRealping);
            await RefreshServersBiz();
        }

        var best = ProfileItems
            .Where(item => item.Delay > 0)
            .OrderBy(item => item.Delay)
            .FirstOrDefault() ?? ProfileItems.FirstOrDefault();
        if (best is null)
        {
            NoticeManager.Instance.Enqueue(ResUI.CheckServerSettings);
            return;
        }

        SelectedProfile = best;
        _config.TunModeItem.EnableTun = true;
        await ConfigHandler.SaveConfig(_config);
        if (best.IndexId == _config.IndexId)
        {
            NoticeManager.Instance.Enqueue(ResUI.DicodeBestRouteConnecting);
        }
        else
        {
            NoticeManager.Instance.Enqueue(ResUI.DicodeBestRouteConnecting);
            await SetDefaultServer(best.IndexId);
        }
        ConnectionStartRequested.Publish();
        await WaitForConnectionAsync();
    }

    private async Task WaitForConnectionAsync()
    {
        for (var attempt = 0; attempt < 40 && !CoreManager.Instance.IsRunning; attempt++)
        {
            await Task.Delay(100);
        }
        IsConnected = CoreManager.Instance.IsRunning;
        NoticeManager.Instance.Enqueue(IsConnected
            ? ResUI.DicodeTunConnectedNotice
            : ResUI.DicodeTunFailedNotice);
    }

    public async Task ShareServerAsync()
    {
        var item = await AppManager.Instance.GetProfileItem(SelectedProfile.IndexId);
        if (item is null)
        {
            NoticeManager.Instance.Enqueue(ResUI.PleaseSelectServer);
            return;
        }
        var url = FmtHandler.GetShareUri(item);
        if (url.IsNullOrEmpty())
        {
            return;
        }

        await ShareServerInteraction.HandleSafe(url);
    }

    private async Task GenGroupAllServer()
    {
        var ret = await ConfigHandler.AddGroupAllServer(_config, SelectedSub);
        if (ret.Success != true)
        {
            NoticeManager.Instance.Enqueue(ResUI.OperationFailed);
            return;
        }
        _pendingSelectIndexId = ret.Data?.ToString();
        await RefreshServers();
    }

    private async Task GenGroupRegionServer()
    {
        var ret = await ConfigHandler.AddGroupRegionServer(_config, SelectedSub);
        if (ret.Success != true)
        {
            NoticeManager.Instance.Enqueue(ResUI.OperationFailed);
            return;
        }
        var indexIdList = ret.Data as List<string>;
        _pendingSelectIndexId = indexIdList?.FirstOrDefault();
        await RefreshServers();
    }

    public async Task SortServer(string colName)
    {
        if (colName.IsNullOrEmpty())
        {
            return;
        }

        _dicHeaderSort.TryAdd(colName, colName != nameof(EServerColName.SpeedVal));
        _dicHeaderSort.TryGetValue(colName, out var asc);
        if (await ConfigHandler.SortServers(_config, _config.SubIndexId, colName, asc) != 0)
        {
            return;
        }
        _dicHeaderSort[colName] = !asc;
        await RefreshServers();
    }

    public async Task RemoveInvalidServerResult()
    {
        var count = await ConfigHandler.RemoveInvalidServerResult(_config, _config.SubIndexId);
        await RefreshServers();
        NoticeManager.Instance.Enqueue(string.Format(ResUI.RemoveInvalidServerResultTip, count));
    }

    //move server
    private async Task MoveToGroup()
    {
        var lstSelected = await GetProfileItems(true);
        if (lstSelected == null)
        {
            return;
        }

        await ConfigHandler.MoveToGroup(_config, lstSelected, SelectedMoveToGroup.Id);
        NoticeManager.Instance.Enqueue(ResUI.OperationSuccess);

        await RefreshServers();
        SelectedMoveToGroup = null;
        SelectedMoveToGroup = new();
    }

    public async Task MoveServer(EMove eMove)
    {
        var lstProfile = ProfileItems?.Select(t => t.IndexId).ToList() ?? [];
        var index = lstProfile.IndexOf(SelectedProfile.IndexId);
        if (index < 0)
        {
            NoticeManager.Instance.Enqueue(ResUI.PleaseSelectServer);
            return;
        }

        if (await ConfigHandler.MoveServer(_config, lstProfile, index, eMove) == 0)
        {
            await RefreshServers();
        }
    }

    public async Task MoveServerTo(int startIndex, ProfileItemModel targetItem)
    {
        var targetIndex = ProfileItems.IndexOf(targetItem);
        if (startIndex >= 0 && targetIndex >= 0 && startIndex != targetIndex)
        {
            var lstProfile = ProfileItems?.Select(t => t.IndexId).ToList() ?? [];
            if (await ConfigHandler.MoveServer(_config, lstProfile, startIndex, EMove.Position, targetIndex) == 0)
            {
                await RefreshServers();
            }
        }
    }

    public async Task ServerSpeedtest(ESpeedActionType actionType, IReadOnlyCollection<ProfileItem>? targetProfiles = null)
    {
        if (IsRefreshing) return;
        var testAll = actionType is ESpeedActionType.FastRealping or ESpeedActionType.Mixedtest or ESpeedActionType.Speedtest or ESpeedActionType.Location or ESpeedActionType.Sanctions;
        if (actionType == ESpeedActionType.FastRealping) actionType = ESpeedActionType.Realping;
        if (actionType == ESpeedActionType.Mixedtest) actionType = ESpeedActionType.Speedtest;
        var lane = actionType is ESpeedActionType.Tcping or ESpeedActionType.Realping or ESpeedActionType.UdpTest ? ESpeedActionType.Realping
            : actionType == ESpeedActionType.Mixedtest ? ESpeedActionType.Speedtest : actionType;
        var gate = _probeLocks.GetOrAdd(lane, _ => new SemaphoreSlim(1, 1));
        if (!await gate.WaitAsync(0))
        {
            if (_probeServices.TryGetValue(lane, out var previous)) previous.ExitLoop();
            await gate.WaitAsync();
        }
        try
        {
            if (IsRefreshing) return;
            List<ProfileItem>? selected;
            // Hold the mutation lock only while taking a DB snapshot. Test processes
            // use independent ports and can run while other diagnostics are active.
            await ProfileOperationCoordinator.Gate.WaitAsync();
            try
            {
                selected = targetProfiles is not null
                    ? JsonUtils.Deserialize<List<ProfileItem>>(JsonUtils.Serialize(targetProfiles))
                    : testAll ? JsonUtils.Deserialize<List<ProfileItem>>(JsonUtils.Serialize(ProfileItems.OrderBy(x => x.Sort)))
                    : await GetProfileItems(false);
            }
            finally { ProfileOperationCoordinator.Gate.Release(); }
            selected = selected?.Where(x => x.ConfigType != EConfigType.Custom && (x.ConfigType.IsComplexType() || x.Port > 0))
                .DistinctBy(x => x.IndexId).ToList();
            if (selected is not { Count: > 0 }) return;
            var run = new ProbeRunModel { Total = selected.Count, Name = actionType switch {
                ESpeedActionType.Location => ResUI.DicodeProbeLocation,
                ESpeedActionType.Sanctions => ResUI.DicodeProbeSanctions,
                ESpeedActionType.Speedtest => ResUI.DicodeProbeSpeed,
                _ => ResUI.DicodeProbeLatency } };
            await OnUiAsync(() => {
                if (_probeRuns.TryGetValue(lane, out var old)) ProbeRuns.Remove(old);
                _probeRuns[lane] = run;
                ProbeRuns.Add(run);
                run.UpdateSummary(ResUI.DicodeProbeRunning);
                return Task.CompletedTask;
            });
            var ids = selected.Select(x => x.IndexId).ToHashSet(StringComparer.Ordinal);
            foreach (var row in ProfileItems.Where(x => ids.Contains(x.IndexId))) SetMetricBusy(row, actionType, true);
            var service = new SpeedtestService(_config, result => OnUiAsync(async () => {
                await ApplyProbeResult(result, actionType);
                var terminal = actionType switch {
                    ESpeedActionType.Location => result.IpInfo,
                    ESpeedActionType.Sanctions => result.SanctionsInfo,
                    ESpeedActionType.Speedtest => result.Speed,
                    _ => result.Delay };
                if (ids.Contains(result.IndexId ?? "") && terminal.IsNotEmpty()
                    && terminal != ResUI.Speedtesting && terminal != ResUI.DicodeChecking && !run.StopRequested)
                    run.Complete(result.IndexId!);
            }));
            _probeServices[lane] = service;
            try { await service.RunLoop(actionType, selected); }
            finally
            {
                _probeServices.TryRemove(lane, out _);
                await OnUiAsync(() => { foreach (var row in ProfileItems.Where(x => ids.Contains(x.IndexId))) SetMetricBusy(row, actionType, false);
                    run.IsRunning = false;
                    run.UpdateSummary(run.StopRequested ? ResUI.SpeedtestingStop : ResUI.SpeedtestingCompleted); return Task.CompletedTask; });
            }
        }
        catch (Exception ex) { Logging.SaveLog("Profile diagnostics", ex); NoticeManager.Instance.Enqueue(ResUI.FailedToRunCore); }
        finally { gate.Release(); }
    }

    private static Task OnUiAsync(Func<Task> action)
    {
        var completion = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        RxSchedulers.MainThreadScheduler.Schedule(async () =>
        {
            try { await action(); completion.TrySetResult(); }
            catch (Exception ex) { completion.TrySetException(ex); }
        });
        return completion.Task;
    }

    public async Task StopDiagnosticsAsync()
    {
        ServerSpeedtestStop();
        foreach (var gate in _probeLocks.Values)
        {
            await gate.WaitAsync();
            gate.Release();
        }
    }

    public void ServerSpeedtestStop()
    {
        foreach (var run in _probeRuns.Values.Where(x => x.IsRunning)) { run.StopRequested = true; run.UpdateSummary(ResUI.DicodeProbeStopping); }
        _securityCts?.Cancel();
        foreach (var service in _probeServices.Values) service.ExitLoop();
    }

    private async Task Export2ClientConfigAsync(bool blClipboard)
    {
        var item = await AppManager.Instance.GetProfileItem(SelectedProfile.IndexId);
        if (item is null)
        {
            NoticeManager.Instance.Enqueue(ResUI.PleaseSelectServer);
            return;
        }

        var (context, validatorResult) = await CoreConfigContextBuilder.Build(_config, item);
        if (NoticeManager.Instance.NotifyValidatorResult(validatorResult) && !validatorResult.Success)
        {
            return;
        }

        if (blClipboard)
        {
            var result = await CoreConfigHandler.GenerateClientConfig(context, null);
            if (result.Success != true)
            {
                NoticeManager.Instance.Enqueue(result.Msg);
            }
            else
            {
                await SetClipboardDataInteraction.HandleSafe((string)result.Data);
                NoticeManager.Instance.SendMessage(ResUI.OperationSuccess);
            }
        }
        else
        {
            await SaveFileDialogInteraction.HandleSafe(item);
        }
    }

    public async Task Export2ClientConfigResult(string fileName, ProfileItem item)
    {
        if (fileName.IsNullOrEmpty())
        {
            return;
        }
        var (context, validatorResult) = await CoreConfigContextBuilder.Build(_config, item);
        if (NoticeManager.Instance.NotifyValidatorResult(validatorResult) && !validatorResult.Success)
        {
            return;
        }
        var result = await CoreConfigHandler.GenerateClientConfig(context, fileName);
        if (result.Success != true)
        {
            NoticeManager.Instance.Enqueue(result.Msg);
        }
        else
        {
            NoticeManager.Instance.SendMessageAndEnqueue(string.Format(ResUI.SaveClientConfigurationIn, fileName));
        }
    }

    public async Task Export2ShareUrlAsync(bool blEncode)
    {
        var lstSelected = await GetProfileItems(true);
        if (lstSelected == null)
        {
            return;
        }

        StringBuilder sb = new();
        foreach (var it in lstSelected)
        {
            var url = FmtHandler.GetShareUri(it);
            if (url.IsNullOrEmpty())
            {
                continue;
            }
            sb.Append(url);
            sb.AppendLine();
        }
        if (sb.Length > 0)
        {
            if (blEncode)
            {
                await SetClipboardDataInteraction.HandleSafe(Utils.Base64Encode(sb.ToString()));
            }
            else
            {
                await SetClipboardDataInteraction.HandleSafe(sb.ToString());
            }
            NoticeManager.Instance.SendMessage(ResUI.BatchExportURLSuccessfully);
        }
    }

    public async Task Export2InnerUrlAsync()
    {
        var lstSelected = await GetProfileItems(true);
        if (lstSelected == null)
        {
            return;
        }

        var result = string.Empty;

        await Task.Run(() =>
        {
            result = InnerFmt.ToUri(lstSelected);
        });

        if (!result.IsNullOrEmpty())
        {
            await SetClipboardDataInteraction.HandleSafe(result);
            NoticeManager.Instance.SendMessage(ResUI.BatchExportURLSuccessfully);
        }
        else
        {
            NoticeManager.Instance.Enqueue(ResUI.OperationFailed);
        }
    }

    #endregion Add Servers

    #region Subscription

    private async Task EditSubAsync(bool blNew)
    {
        SubItem item;
        if (blNew)
        {
            item = new();
        }
        else
        {
            item = await AppManager.Instance.GetSubItem(_config.SubIndexId);
            if (item is null)
            {
                return;
            }
        }
        var subEditViewModel = new SubEditViewModel(item);
        if (await AppManager.Instance.WindowDialog.ShowDialogAsync(subEditViewModel) == true)
        {
            await RefreshSubscriptions();
            await SubSelectedChangedAsync();
        }
    }

    private async Task DeleteSubAsync()
    {
        var item = await AppManager.Instance.GetSubItem(_config.SubIndexId);
        if (item is null)
        {
            return;
        }

        if (await ShowYesNoInteraction.HandleSafe(ResUI.RemoveServer) == false)
        {
            return;
        }
        await ConfigHandler.DeleteSubItem(_config, item.Id);

        await RefreshSubscriptions();
        await SubSelectedChangedAsync();
    }

    #endregion Subscription
}
