namespace ServiceLib.ViewModels;

public partial class SanctionServiceRow : ReactiveObject
{
    [Reactive] public partial bool Enabled { get; set; }
    [Reactive] public partial string Name { get; set; }
    [Reactive] public partial string Url { get; set; }
    [Reactive] public partial bool Strict { get; set; }
}

public partial class SanctionsServicesViewModel : MyReactiveObject
{
    private readonly ObservableCollection<SanctionServiceRow> _allRows = [];

    public ObservableCollection<SanctionServiceRow> VisibleRows { get; } = [];

    [Reactive]
    public partial string SearchText { get; set; }

    public ReactiveCommand<SanctionServiceRow, RxVoid> DeleteRowCmd { get; }
    public ReactiveCommand<RxVoid, RxVoid> AddRowCmd { get; }
    public ReactiveCommand<RxVoid, RxVoid> EnableAllCmd { get; }
    public ReactiveCommand<RxVoid, RxVoid> ResetDefaultsCmd { get; }
    public ReactiveCommand<RxVoid, bool> SaveCmd { get; }

    public SanctionsServicesViewModel()
    {
        _config = AppManager.Instance.Config;

        foreach (var service in ConnectionHandler.GetSanctionServices())
        {
            _allRows.Add(new SanctionServiceRow
            {
                Enabled = service.Enabled,
                Name = service.Name,
                Url = service.Url,
                Strict = service.Strict,
            });
        }
        RebuildVisible();

        DeleteRowCmd = ReactiveCommand.Create<SanctionServiceRow, RxVoid>(row =>
        {
            _allRows.Remove(row);
            VisibleRows.Remove(row);
            return RxVoid.Default;
        });

        AddRowCmd = ReactiveCommand.Create<RxVoid, RxVoid>(_ =>
        {
            var row = new SanctionServiceRow { Enabled = true, Name = string.Empty, Url = "https://", Strict = false };
            _allRows.Add(row);
            VisibleRows.Add(row);
            return RxVoid.Default;
        });

        EnableAllCmd = ReactiveCommand.Create<RxVoid, RxVoid>(_ =>
        {
            foreach (var row in _allRows)
            {
                row.Enabled = true;
            }
            return RxVoid.Default;
        });

        ResetDefaultsCmd = ReactiveCommand.Create<RxVoid, RxVoid>(_ =>
        {
            _allRows.Clear();
            VisibleRows.Clear();
            foreach (var service in SanctionsDefaults.Services)
            {
                var row = new SanctionServiceRow
                {
                    Enabled = service.Enabled,
                    Name = service.Name,
                    Url = service.Url,
                    Strict = service.Strict,
                };
                _allRows.Add(row);
                VisibleRows.Add(row);
            }
            return RxVoid.Default;
        });

        this.WhenAnyValue(x => x.SearchText)
            .Subscribe(_ => RebuildVisible());

        SaveCmd = ReactiveCommand.CreateFromTask(async () =>
        {
            _config.SanctionsItem ??= new SanctionsItem();
            _config.SanctionsItem.Services = _allRows
                .Where(r => r.Name.Trim().IsNotEmpty() && r.Url.Trim().IsNotEmpty())
                .Select(r => new SanctionServiceItem
                {
                    Enabled = r.Enabled,
                    Name = r.Name.Trim(),
                    Url = r.Url.Trim(),
                    Strict = r.Strict,
                })
                .ToList();
            await ConfigHandler.SaveConfig(_config);
            return true;
        });
    }

    private void RebuildVisible()
    {
        var filter = SearchText?.Trim() ?? string.Empty;
        VisibleRows.Clear();
        foreach (var row in _allRows)
        {
            if (filter.IsNullOrEmpty()
                || row.Name.Contains(filter, StringComparison.OrdinalIgnoreCase)
                || row.Url.Contains(filter, StringComparison.OrdinalIgnoreCase))
            {
                VisibleRows.Add(row);
            }
        }
    }
}
