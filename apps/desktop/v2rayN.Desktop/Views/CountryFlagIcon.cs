using Avalonia;
using Avalonia.Controls;
using Avalonia.Media;
using System.Text.RegularExpressions;

namespace v2rayN.Desktop.Views;

public sealed class CountryFlagIcon : Control
{
    public static readonly StyledProperty<string?> SourceTextProperty =
        AvaloniaProperty.Register<CountryFlagIcon, string?>(nameof(SourceText));

    public string? SourceText
    {
        get => GetValue(SourceTextProperty);
        set => SetValue(SourceTextProperty, value);
    }

    static CountryFlagIcon()
    {
        AffectsRender<CountryFlagIcon>(SourceTextProperty);
    }

    public override void Render(DrawingContext context)
    {
        base.Render(context);
        var rect = new Rect(Bounds.Size).Deflate(0.5);
        if (rect.Width <= 0 || rect.Height <= 0) return;
        var code = ExtractCode(SourceText);
        var clip = new RoundedRect(rect, 3);
        using (context.PushClip(clip))
        {
            DrawFlag(context, rect, code);
        }
        context.DrawRectangle(null, new Pen(new SolidColorBrush(Color.Parse("#55000000")), 1), clip);
    }

    private static string ExtractCode(string? value)
    {
        if (string.IsNullOrWhiteSpace(value)) return "";
        var match = Regex.Match(value, @"(?<![A-Za-z])[A-Za-z]{2}(?![A-Za-z])");
        return match.Success ? match.Value.ToUpperInvariant() : "";
    }

    private static void DrawFlag(DrawingContext c, Rect r, string code)
    {
        static IBrush B(string hex) => new SolidColorBrush(Color.Parse(hex));
        void H(string a, string b, string d)
        {
            c.DrawRectangle(B(a), null, new Rect(r.X, r.Y, r.Width, r.Height / 3));
            c.DrawRectangle(B(b), null, new Rect(r.X, r.Y + r.Height / 3, r.Width, r.Height / 3));
            c.DrawRectangle(B(d), null, new Rect(r.X, r.Y + 2 * r.Height / 3, r.Width, r.Height / 3));
        }
        void V(string a, string b, string d)
        {
            c.DrawRectangle(B(a), null, new Rect(r.X, r.Y, r.Width / 3, r.Height));
            c.DrawRectangle(B(b), null, new Rect(r.X + r.Width / 3, r.Y, r.Width / 3, r.Height));
            c.DrawRectangle(B(d), null, new Rect(r.X + 2 * r.Width / 3, r.Y, r.Width / 3, r.Height));
        }

        switch (code)
        {
            case "JP":
                c.DrawRectangle(B("#FFFFFF"), null, r);
                c.DrawEllipse(B("#BC002D"), null, r.Center, r.Height * .25, r.Height * .25);
                break;
            case "SG":
                H("#EF3340", "#EF3340", "#FFFFFF");
                c.DrawEllipse(B("#FFFFFF"), null, new Point(r.X + r.Width * .25, r.Y + r.Height * .27), r.Height * .18, r.Height * .18);
                c.DrawEllipse(B("#EF3340"), null, new Point(r.X + r.Width * .30, r.Y + r.Height * .27), r.Height * .14, r.Height * .14);
                break;
            case "US":
                for (var i = 0; i < 7; i++) c.DrawRectangle(B(i % 2 == 0 ? "#B22234" : "#FFFFFF"), null, new Rect(r.X, r.Y + i * r.Height / 7, r.Width, r.Height / 7));
                c.DrawRectangle(B("#3C3B6E"), null, new Rect(r.X, r.Y, r.Width * .42, r.Height * .55));
                break;
            case "DE": H("#111111", "#DD0000", "#FFCE00"); break;
            case "IR": H("#239F40", "#FFFFFF", "#DA0000"); break;
            case "NL": H("#AE1C28", "#FFFFFF", "#21468B"); break;
            case "RU": H("#FFFFFF", "#0039A6", "#D52B1E"); break;
            case "FR": V("#0055A4", "#FFFFFF", "#EF4135"); break;
            case "IT": V("#009246", "#FFFFFF", "#CE2B37"); break;
            case "IE": V("#169B62", "#FFFFFF", "#FF883E"); break;
            case "BE": V("#111111", "#FDDA24", "#EF3340"); break;
            case "AE": H("#00732F", "#FFFFFF", "#000000"); c.DrawRectangle(B("#FF0000"), null, new Rect(r.X, r.Y, r.Width * .25, r.Height)); break;
            case "TR": c.DrawRectangle(B("#E30A17"), null, r); c.DrawEllipse(B("#FFFFFF"), null, new Point(r.X + r.Width * .42, r.Center.Y), r.Height * .24, r.Height * .24); c.DrawEllipse(B("#E30A17"), null, new Point(r.X + r.Width * .48, r.Center.Y), r.Height * .19, r.Height * .19); break;
            case "CH": c.DrawRectangle(B("#D52B1E"), null, r); c.DrawRectangle(B("#FFFFFF"), null, new Rect(r.X + r.Width * .43, r.Y + r.Height * .2, r.Width * .14, r.Height * .6)); c.DrawRectangle(B("#FFFFFF"), null, new Rect(r.X + r.Width * .28, r.Y + r.Height * .4, r.Width * .44, r.Height * .2)); break;
            case "GB": c.DrawRectangle(B("#012169"), null, r); c.DrawRectangle(B("#FFFFFF"), null, new Rect(r.X, r.Y + r.Height * .39, r.Width, r.Height * .22)); c.DrawRectangle(B("#FFFFFF"), null, new Rect(r.X + r.Width * .42, r.Y, r.Width * .16, r.Height)); c.DrawRectangle(B("#C8102E"), null, new Rect(r.X, r.Y + r.Height * .44, r.Width, r.Height * .12)); c.DrawRectangle(B("#C8102E"), null, new Rect(r.X + r.Width * .46, r.Y, r.Width * .08, r.Height)); break;
            case "FI": c.DrawRectangle(B("#FFFFFF"), null, r); c.DrawRectangle(B("#003580"), null, new Rect(r.X, r.Y + r.Height * .4, r.Width, r.Height * .2)); c.DrawRectangle(B("#003580"), null, new Rect(r.X + r.Width * .32, r.Y, r.Width * .14, r.Height)); break;
            case "SE": c.DrawRectangle(B("#006AA7"), null, r); c.DrawRectangle(B("#FECC00"), null, new Rect(r.X, r.Y + r.Height * .4, r.Width, r.Height * .2)); c.DrawRectangle(B("#FECC00"), null, new Rect(r.X + r.Width * .32, r.Y, r.Width * .14, r.Height)); break;
            default: H("#607D8B", "#ECEFF1", "#455A64"); break;
        }
    }
}
