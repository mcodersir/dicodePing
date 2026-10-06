namespace ServiceLib.ViewModels;

public partial class SpoSourceRow : ReactiveObject
{
    [Reactive] public partial bool Enabled { get; set; }
    [Reactive] public partial string Name { get; set; }
    [Reactive] public partial string Url { get; set; }
}

public partial class SpoSourcesViewModel : MyReactiveObject
{
    private readonly ObservableCollection<SpoSourceRow> _allRows = [];

    public ObservableCollection<SpoSourceRow> VisibleRows { get; } = [];

    [Reactive]
    public partial string SearchText { get; set; }

    public ReactiveCommand<SpoSourceRow, RxVoid> DeleteRowCmd { get; }
    public ReactiveCommand<RxVoid, RxVoid> AddRowCmd { get; }
    public ReactiveCommand<RxVoid, RxVoid> EnableAllCmd { get; }
    public ReactiveCommand<RxVoid, RxVoid> ResetDefaultsCmd { get; }
    public ReactiveCommand<RxVoid, bool> SaveCmd { get; }

    public SpoSourcesViewModel()
    {
        _config = AppManager.Instance.Config;

        foreach (var source in SpoSourcesService.GetSources())
        {
            _allRows.Add(new SpoSourceRow
            {
                Enabled = source.Enabled,
                Name = source.Name,
                Url = source.Url,
            });
        }
        RebuildVisible();

        DeleteRowCmd = ReactiveCommand.Create<SpoSourceRow, RxVoid>(row =>
        {
            _allRows.Remove(row);
            VisibleRows.Remove(row);
            return RxVoid.Default;
        });

        AddRowCmd = ReactiveCommand.Create<RxVoid, RxVoid>(_ =>
        {
            var row = new SpoSourceRow { Enabled = true, Name = string.Empty, Url = "https://" };
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
            foreach (var source in SpoSourceDefaults.Sources)
            {
                var row = new SpoSourceRow
                {
                    Enabled = source.Enabled,
                    Name = source.Name,
                    Url = source.Url,
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
            _config.SpoSourcesItem ??= new SpoSourcesItem();
            _config.SpoSourcesItem.Sources = _allRows
                .Where(r => r.Name.Trim().IsNotEmpty() && r.Url.Trim().IsNotEmpty())
                .Select(r => new SpoSourceItem
                {
                    Enabled = r.Enabled,
                    Name = r.Name.Trim(),
                    Url = r.Url.Trim(),
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
