using Avalonia.Controls.Notifications;
using Avalonia.Controls.Primitives;
using AvaloniaEdit;
using Semi.Avalonia;

namespace v2rayN.Desktop.ViewModels;

public partial class ThemeSettingViewModel : MyReactiveObject
{
    [Reactive] public partial string CurrentTheme { get; set; }

    [Reactive] public partial int CurrentFontSize { get; set; }

    [Reactive] public partial string CurrentLanguage { get; set; }

    public ThemeSettingViewModel()
    {
        _config = AppManager.Instance.Config;

        BindingUI();
        RestoreUI();
    }

    private void RestoreUI()
    {
        ModifyTheme();
        ModifyFontFamily();
        ModifyFontSize();
    }

    private void BindingUI()
    {
        CurrentTheme = Enum.TryParse<ETheme>(_config.UiItem.CurrentTheme, true, out var savedTheme)
            ? savedTheme.ToString()
            : nameof(ETheme.FollowSystem);
        CurrentFontSize = _config.UiItem.CurrentFontSize;
        CurrentLanguage = _config.UiItem.CurrentLanguage;

        this.WhenAnyValue(x => x.CurrentTheme)
            .Subscribe(c =>
            {
                if (_config.UiItem.CurrentTheme != CurrentTheme)
                {
                    _config.UiItem.CurrentTheme = CurrentTheme;
                    ModifyTheme();
                    _ = ConfigHandler.SaveConfig(_config);
                }
            });

        this.WhenAnyValue(
                x => x.CurrentFontSize,
                y => y > 0)
            .Subscribe(c =>
            {
                if (_config.UiItem.CurrentFontSize != CurrentFontSize && CurrentFontSize >= Global.MinFontSize)
                {
                    _config.UiItem.CurrentFontSize = CurrentFontSize;
                    ModifyFontSize();
                    _ = ConfigHandler.SaveConfig(_config);
                }
            });

        this.WhenAnyValue(
                x => x.CurrentLanguage,
                y => y != null && !y.IsNullOrEmpty())
            .Subscribe(c =>
            {
                if (CurrentLanguage.IsNotEmpty() && _config.UiItem.CurrentLanguage != CurrentLanguage)
                {
                    _config.UiItem.CurrentLanguage = CurrentLanguage;
                    Thread.CurrentThread.CurrentUICulture = new(CurrentLanguage);
                    _ = ConfigHandler.SaveConfig(_config);
                    NoticeManager.Instance.Enqueue(ResUI.NeedRebootTips);
                }
            });
    }

    private void ModifyTheme()
    {
        var app = Application.Current;
        if (app is not null)
        {
            var requestedVariant = CurrentTheme switch
            {
                nameof(ETheme.Dark) => ThemeVariant.Dark,
                nameof(ETheme.Light) => ThemeVariant.Light,
                nameof(ETheme.Aquatic) => SemiTheme.Aquatic,
                nameof(ETheme.Desert) => SemiTheme.Desert,
                nameof(ETheme.Dusk) => SemiTheme.Dusk,
                nameof(ETheme.NightSky) => SemiTheme.NightSky,
                _ => ThemeVariant.Default,
            };

            // Semi custom variants and Avalonia built-in variants do not share the
            // same resource ancestry. Apply both the variant and one explicit palette
            // so a live switch can never mix light surfaces with dark foregrounds.
            app.RequestedThemeVariant = requestedVariant;
            if (app.ApplicationLifetime is IClassicDesktopStyleApplicationLifetime desktop)
            {
                foreach (var window in desktop.Windows)
                {
                    window.RequestedThemeVariant = requestedVariant;
                }
            }

            ApplyDicodePalette(app, CurrentTheme, app.ActualThemeVariant == ThemeVariant.Dark);
            Dispatcher.UIThread.Post(
                () => ApplyDicodePalette(app, CurrentTheme, app.ActualThemeVariant == ThemeVariant.Dark),
                DispatcherPriority.Render);
        }
    }

    private static void ApplyDicodePalette(Application app, string themeName, bool systemIsDark)
    {
        var palette = themeName switch
        {
            nameof(ETheme.Dark) => ("#0D141C", "#121B25", "#18232F", "#293746", "#F2F5F8", "#ADB8C5", "#1D3A58", "#63A9FF"),
            nameof(ETheme.Aquatic) => ("#071B20", "#0C252B", "#123139", "#24505A", "#EAFBFC", "#A9D0D4", "#164957", "#48C6D4"),
            nameof(ETheme.Desert) => ("#FBF5E9", "#FFFDF8", "#F5EBD9", "#E2D2B8", "#2B241B", "#746653", "#F2DFC0", "#B8762D"),
            nameof(ETheme.Dusk) => ("#1B1422", "#241A2D", "#30213B", "#503B5E", "#FAF3FF", "#C8B3D2", "#49305D", "#C58AE2"),
            nameof(ETheme.NightSky) => ("#080F20", "#0E1930", "#15233E", "#293D60", "#F2F6FF", "#AAB9D3", "#183A66", "#72A8FF"),
            nameof(ETheme.FollowSystem) when systemIsDark => ("#0D141C", "#121B25", "#18232F", "#293746", "#F2F5F8", "#ADB8C5", "#1D3A58", "#63A9FF"),
            _ => ("#F5F7FA", "#FFFFFF", "#F9FAFC", "#DCE2EA", "#17212B", "#5F6B7A", "#E0EDFF", "#3278D3"),
        };

        SetBrush(app, "DicodePageBackground", palette.Item1);
        SetBrush(app, "DicodeSurface", palette.Item2);
        SetBrush(app, "DicodeSurfaceElevated", palette.Item3);
        SetBrush(app, "DicodeBorder", palette.Item4);
        SetBrush(app, "DicodeTextPrimary", palette.Item5);
        SetBrush(app, "DicodeTextSecondary", palette.Item6);
        SetBrush(app, "DicodeSelection", palette.Item7);
        SetBrush(app, "DicodeAccent", palette.Item8);
    }

    private static void SetBrush(Application app, string key, string color) =>
        app.Resources[key] = new SolidColorBrush(Color.Parse(color));

    private void ModifyFontSize()
    {
        double size = CurrentFontSize;
        if (size < Global.MinFontSize)
        {
            return;
        }

        Style style = new(x => Selectors.Or(
            x.OfType<Button>(),
            x.OfType<TextBox>(),
            x.OfType<TextBlock>(),
            x.OfType<SelectableTextBlock>(),
            x.OfType<Menu>(),
            x.OfType<ContextMenu>(),
            x.OfType<DataGridRow>(),
            x.OfType<ListBoxItem>(),
            x.OfType<HeaderedContentControl>(),
            x.OfType<TextEditor>()
        ));
        style.Add(new Setter()
        {
            Property = TemplatedControl.FontSizeProperty,
            Value = size,
        });
        Application.Current?.Styles.Add(style);

        ModifyFontSizeEx(size);
    }

    private void ModifyFontSizeEx(double size)
    {
        //DataGrid
        var rowHeight = 20 + (size / 2);
        var style = new Style(x => x.OfType<DataGrid>());
        style.Add(new Setter(DataGrid.RowHeightProperty, rowHeight));
        Application.Current?.Styles.Add(style);
    }

    private void ModifyFontFamily()
    {
        var currentFontFamily = "avares://DicodePing/Assets/Fonts#Open Sans, avares://DicodePing/Assets/Fonts#Vazirmatn";

        try
        {
            Style style = new(x => Selectors.Or(
                x.OfType<Button>(),
                x.OfType<TextBox>(),
                x.OfType<TextBlock>(),
                x.OfType<SelectableTextBlock>(),
                x.OfType<Menu>(),
                x.OfType<ContextMenu>(),
                x.OfType<DataGridRow>(),
                x.OfType<ListBoxItem>(),
                x.OfType<HeaderedContentControl>(),
                x.OfType<WindowNotificationManager>(),
                x.OfType<TextEditor>()
            ));
            style.Add(new Setter()
            {
                Property = TemplatedControl.FontFamilyProperty,
                Value = new FontFamily(currentFontFamily),
            });
            Application.Current?.Styles.Add(style);
        }
        catch (Exception ex)
        {
            Logging.SaveLog("ModifyFontFamily", ex);
        }
    }
}
