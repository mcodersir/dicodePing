namespace ServiceLib.ViewModels;

public partial class DomainFilterSettingViewModel : MyReactiveObject
{
    [Reactive] public partial bool OnlyListedDomains { get; set; }
    [Reactive] public partial bool BypassListedDomains { get; set; }
    [Reactive] public partial string Domains { get; set; }

    public ReactiveCommand<RxVoid, bool> SaveCmd { get; }

    public DomainFilterSettingViewModel()
    {
        _config = AppManager.Instance.Config;
        OnlyListedDomains = _config.RoutingBasicItem.DomainFilterMode == "only";
        BypassListedDomains = _config.RoutingBasicItem.DomainFilterMode == "bypass";
        Domains = string.Join(Environment.NewLine, _config.RoutingBasicItem.DomainFilterList ?? []);

        this.WhenAnyValue(x => x.OnlyListedDomains).Skip(1).Where(x => x)
            .Subscribe(_ => BypassListedDomains = false);
        this.WhenAnyValue(x => x.BypassListedDomains).Skip(1).Where(x => x)
            .Subscribe(_ => OnlyListedDomains = false);

        SaveCmd = ReactiveCommand.CreateFromTask(async () =>
        {
            _config.RoutingBasicItem.DomainFilterMode = OnlyListedDomains ? "only" : BypassListedDomains ? "bypass" : "off";
            _config.RoutingBasicItem.DomainFilterList = Domains
                .Split(['\r', '\n', ',', ' ', '\t'], StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
                .Select(x => x.Trim().TrimStart('.'))
                .Where(x => x.IsNotEmpty())
                .Distinct(StringComparer.OrdinalIgnoreCase)
                .ToList();
            await ConfigHandler.SaveConfig(_config);
            return true;
        });
    }
}
