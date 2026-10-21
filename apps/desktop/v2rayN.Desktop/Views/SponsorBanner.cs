using Avalonia.Layout;
using Avalonia.Threading;
using ServiceLib.Services;
namespace v2rayN.Desktop.Views;

public sealed class SponsorBanner : UserControl
{
    public string Placement { get; set; } = "home";
    private CancellationTokenSource? _lifetime;
    private readonly DispatcherTimer _timer = new() { Interval = TimeSpan.FromMinutes(15) };
    public SponsorBanner()
    {
        IsVisible = false;
        _timer.Tick += async (_, _) => await Refresh();
        AttachedToVisualTree += async (_, _) => { _lifetime = new(); _timer.Start(); await Refresh(); };
        DetachedFromVisualTree += (_, _) => { _timer.Stop(); _lifetime?.Cancel(); };
    }
    private async Task Refresh()
    {
        var lifetime = _lifetime;
        if (lifetime is null) return;
        var fa = FoxUi.T("fa", "en") == "fa";
        var ad = await RemoteAds.LoadAsync(Placement, fa, lifetime.Token);
        if (lifetime.IsCancellationRequested) return;
        IsVisible = ad is not null;
        if (ad is null) { Content = null; return; }
        var link = new Button { Content = ad.Title, HorizontalAlignment = HorizontalAlignment.Stretch };
        link.Click += (_, _) => ProcUtils.ProcessStart(ad.Url);
        Content = new Border { Padding = new Thickness(12), CornerRadius = new CornerRadius(10), BorderThickness = new Thickness(1), Child = new StackPanel {
            Spacing = 5, Children = { new TextBlock { Text = fa ? "تبلیغ" : "Sponsored", FontSize = 11, Opacity = .65 }, link,
            new TextBlock { Text = ad.Body, TextWrapping = TextWrapping.Wrap } } } };
    }
}
