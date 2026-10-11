using Avalonia;
using Avalonia.Controls;
using Avalonia.Media;
using Avalonia.Media.Imaging;
using Avalonia.Platform;
using System.Collections.Concurrent;
using ServiceLib.Services;

namespace v2rayN.Desktop.Views;

/// <summary>Local flag assets; never infer an exit country from a profile's name.</summary>
public sealed class CountryFlagIcon : Control
{
    public static readonly StyledProperty<string?> SourceTextProperty =
        AvaloniaProperty.Register<CountryFlagIcon, string?>(nameof(SourceText));
    private static readonly ConcurrentDictionary<string, Bitmap> Flags = new();
    public string? SourceText { get => GetValue(SourceTextProperty); set => SetValue(SourceTextProperty, value); }
    static CountryFlagIcon() => AffectsRender<CountryFlagIcon>(SourceTextProperty);
    public override void Render(DrawingContext context)
    {
        base.Render(context);
        var rect = new Rect(Bounds.Size).Deflate(0.5);
        if (rect.Width <= 0 || rect.Height <= 0) return;
        var code = CountryCodes.FromLocation(SourceText).ToLowerInvariant();
        var uri = new Uri($"avares://DicodePing/Assets/Flags/{code}.png");
        if (code.Length == 2 && AssetLoader.Exists(uri))
        {
            var flag = Flags.GetOrAdd(code, _ => new Bitmap(AssetLoader.Open(uri)));
            using (context.PushClip(new RoundedRect(rect, 3)))
                context.DrawImage(flag, new Rect(flag.Size), rect);
        }
        else
        {
            // Unknown remains unknown; a globe is preferable to an invented country.
            var pen = new Pen(new SolidColorBrush(Color.Parse("#9CA8B8")), 1.2);
            var r = Math.Min(rect.Width, rect.Height) * .43;
            context.DrawEllipse(null, pen, rect.Center, r, r);
            context.DrawEllipse(null, pen, rect.Center, r * .45, r);
            context.DrawLine(pen, new Point(rect.Center.X-r,rect.Center.Y), new Point(rect.Center.X+r,rect.Center.Y));
        }
    }
}
