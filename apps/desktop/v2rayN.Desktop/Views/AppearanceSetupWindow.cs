using System.Globalization;
using System.IO;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;
using ServiceLib;
using ServiceLib.Handler;
using ServiceLib.Manager;

namespace v2rayN.Desktop.Views;

public sealed class AppearanceSetupWindow : Window
{
    public static string MarkerPath => Utils.GetConfigPath("appearance-setup-503.done");
    public AppearanceSetupWindow(Action completed)
    {
        Title = "DicodePing · Welcome";
        Width = 520; Height = 620; MinWidth = 320; MinHeight = 360;
        WindowStartupLocation = WindowStartupLocation.CenterScreen;
        var config = AppManager.Instance.Config;
        var languages = Global.LanguageOptions;
        var language = new ComboBox { ItemsSource = languages.Select(x => x.Display).ToList(), HorizontalAlignment = HorizontalAlignment.Stretch };
        language.SelectedIndex = Math.Max(0, languages.FindIndex(x => x.Value == config.UiItem.CurrentLanguage));
        var theme = new ComboBox { ItemsSource = new[] { "System · سیستم", "Light · روشن", "Dark · تیره" }, SelectedIndex = 0, HorizontalAlignment = HorizontalAlignment.Stretch };
        var next = new Button { Content = "Continue · ادامه", HorizontalAlignment = HorizontalAlignment.Stretch, HorizontalContentAlignment = HorizontalAlignment.Center, MinHeight = 48 };
        var error = new TextBlock { TextWrapping = TextWrapping.Wrap };
        next.Click += async (_, _) => {
            next.IsEnabled = false;
            try {
                var selected = languages[Math.Max(0, language.SelectedIndex)].Value;
                config.UiItem.CurrentLanguage = selected;
                config.UiItem.CurrentTheme = theme.SelectedIndex switch { 1 => "Light", 2 => "Dark", _ => "FollowSystem" };
                await ConfigHandler.SaveConfig(config);
                CultureInfo.DefaultThreadCurrentUICulture = new CultureInfo(selected);
                CultureInfo.CurrentUICulture = new CultureInfo(selected);
                await File.WriteAllTextAsync(MarkerPath, "5.0.3");
                completed();
                Close();
            } catch (Exception ex) { error.Text = "Could not save preferences. Please retry."; Logging.SaveLog("Appearance setup", ex); next.IsEnabled = true; }
        };
        Content = new ScrollViewer { Content = new StackPanel { Margin = new Thickness(28), Spacing = 18, Children = {
            new TextBlock { Text = "Welcome to DicodePing", FontSize = 26, FontWeight = FontWeight.SemiBold, TextWrapping = TextWrapping.Wrap },
            new TextBlock { Text = "زبان و ظاهر · Language & appearance", TextWrapping = TextWrapping.Wrap },
            new TextBlock { Text = "Language · زبان" }, language,
            new TextBlock { Text = "Appearance · ظاهر" }, theme, error, next
        } } };
    }
}
