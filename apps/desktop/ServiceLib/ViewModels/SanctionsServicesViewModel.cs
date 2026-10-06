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
    public ObservableCollection<SanctionServiceRow> Rows { get; } = [];

    public ReactiveCommand<SanctionServiceRow, RxVoid> DeleteRowCmd { get; }
    public ReactiveCommand<RxVoid, RxVoid> AddRowCmd { get; }
    public ReactiveCommand<RxVoid, RxVoid> ResetDefaultsCmd { get; }
    public ReactiveCommand<RxVoid, bool> SaveCmd { get; }

    public SanctionsServicesViewModel()
    {
        _config = AppManager.Instance.Config;

        foreach (var service in ConnectionHandler.GetSanctionServices())
        {
            Rows.Add(new SanctionServiceRow
            {
                Enabled = service.Enabled,
                Name = service.Name,
                Url = service.Url,
                Strict = service.Strict,
            });
        }

        DeleteRowCmd = ReactiveCommand.Create<SanctionServiceRow, RxVoid>(row =>
        {
            Rows.Remove(row);
            return RxVoid.Default;
        });

        AddRowCmd = ReactiveCommand.Create<RxVoid, RxVoid>(_ =>
        {
            Rows.Add(new SanctionServiceRow { Enabled = true, Name = string.Empty, Url = "https://", Strict = false });
            return RxVoid.Default;
        });

        ResetDefaultsCmd = ReactiveCommand.Create<RxVoid, RxVoid>(_ =>
        {
            Rows.Clear();
            foreach (var service in SanctionsDefaults.Services)
            {
                Rows.Add(new SanctionServiceRow
                {
                    Enabled = service.Enabled,
                    Name = service.Name,
                    Url = service.Url,
                    Strict = service.Strict,
                });
            }
            return RxVoid.Default;
        });

        SaveCmd = ReactiveCommand.CreateFromTask(async () =>
        {
            _config.SanctionsItem ??= new SanctionsItem();
            _config.SanctionsItem.Services = Rows
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
}
