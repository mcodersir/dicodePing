using Avalonia.Layout;
using Avalonia.Threading;
using Avalonia.Media.Imaging;
using ServiceLib.Services;
namespace v2rayN.Desktop.Views;

public sealed class SponsorBanner : UserControl
{
    public string Placement { get; set; } = "home";
    private CancellationTokenSource? _lifetime;
    private readonly DispatcherTimer _timer = new() { Interval = TimeSpan.FromSeconds(1) };
    private DateTime _nextRefresh;
    private bool _loading;
    private Bitmap? _bitmap;
    public SponsorBanner()
    {
        IsVisible = false;
        _timer.Tick += async (_, _) => await Refresh();
        AttachedToVisualTree += async (_, _) => { _lifetime = new(); _nextRefresh = DateTime.MinValue; _timer.Start(); await Refresh(); };
        DetachedFromVisualTree += (_, _) => { _timer.Stop(); _lifetime?.Cancel(); _bitmap?.Dispose(); _bitmap = null; Content = null; };
    }
    private async Task Refresh()
    {
        var lifetime = _lifetime;
        if (lifetime is null || lifetime.IsCancellationRequested) return;
        if (!CoreManager.Instance.IsRunning) { IsVisible = false; _nextRefresh = DateTime.MinValue; return; }
        if (_loading || DateTime.UtcNow < _nextRefresh) return;
        _loading = true;
        try {
            var fa = FoxUi.T("fa", "en") == "fa";
            var ad = await RemoteAds.LoadAsync(Placement, fa, lifetime.Token);
            if (lifetime.IsCancellationRequested) return;
            _nextRefresh = DateTime.UtcNow.AddMinutes(15);
            _bitmap?.Dispose(); _bitmap = null;
            if (ad is null) { IsVisible = false; Content = null; return; }
            var contents = new StackPanel { Spacing = 3 };
            contents.Children.Add(new TextBlock { Text = (fa ? "تبلیغ · " : "Ad · ") + ad.Title, FontSize = 12,
                TextTrimming = TextTrimming.CharacterEllipsis, MaxLines = 1 });
            if (ad.ImageUrl is not null) {
                try {
                    using var handler = new System.Net.Http.HttpClientHandler { AllowAutoRedirect = false };
                    using var client = new System.Net.Http.HttpClient(handler) { Timeout = TimeSpan.FromSeconds(4), MaxResponseContentBufferSize = 1048576 };
                    var bytes = await client.GetByteArrayAsync(ad.ImageUrl, lifetime.Token);
                    var bitmap = await Task.Run(() => { using var stream = new MemoryStream(bytes); return Bitmap.DecodeToWidth(stream, 960); }, lifetime.Token);
                    if (lifetime.IsCancellationRequested) { bitmap.Dispose(); return; }
                    _bitmap = bitmap;
                    contents.Children.Add(new Image { Source = bitmap, MaxHeight = 88, Stretch = Stretch.Uniform });
                } catch (Exception) { /* Keep the labelled text link if a banner fails. */ }
            } else if (!string.IsNullOrWhiteSpace(ad.Body)) contents.Children.Add(new TextBlock {
                Text = ad.Body, FontSize = 11, Opacity = .8, MaxLines = 1, TextTrimming = TextTrimming.CharacterEllipsis });
            var link = new Button { Content = contents, Padding = new Thickness(10, 6), HorizontalContentAlignment = HorizontalAlignment.Stretch,
                HorizontalAlignment = HorizontalAlignment.Stretch, CornerRadius = new CornerRadius(8), Margin = new Thickness(0, 3) };
            link.Click += (_, _) => ProcUtils.ProcessStart(ad.Url);
            Content = link;
            IsVisible = CoreManager.Instance.IsRunning;
        } finally { _loading = false; }
    }
}
