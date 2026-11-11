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
        var theme = new ComboBox { ItemsSource = new[] { "System · سیستم", "Light · روشن", "Dark · تیره" }, SelectedIndex = config.UiItem.CurrentTheme switch { "Light" => 1, "Dark" => 2, _ => 0 }, HorizontalAlignment = HorizontalAlignment.Stretch };
        var next = new Button { Name = "CompleteAppearanceSetup", Content = "Continue · ادامه", HorizontalAlignment = HorizontalAlignment.Stretch, HorizontalContentAlignment = HorizontalAlignment.Center, MinHeight = 48 };
        var error = new TextBlock { TextWrapping = TextWrapping.Wrap };
        next.Click += async (_, _) => {
            next.IsEnabled = false;
            try {
                var selected = languages[Math.Max(0, language.SelectedIndex)].Value;
                var culture = new CultureInfo(selected); // Validate before persisting a locale.
                config.UiItem.CurrentLanguage = selected;
                config.UiItem.CurrentTheme = theme.SelectedIndex switch { 1 => "Light", 2 => "Dark", _ => "FollowSystem" };
                if (await ConfigHandler.SaveConfig(config) != 0) throw new IOException("Could not persist appearance preferences.");
                CultureInfo.DefaultThreadCurrentUICulture = culture;
                CultureInfo.CurrentUICulture = culture;
                ServiceLib.Resx.ResUI.Culture = CultureInfo.CurrentUICulture;
                await File.WriteAllTextAsync(MarkerPath, "5.0.3");
                completed();
                Close();
            } catch (Exception ex) { error.Text = "Could not save preferences. Please retry."; Logging.SaveLog("Appearance setup", ex); next.IsEnabled = true; }
        };
        var form = new StackPanel { Margin = new Thickness(28), Spacing = 18, Children = {
            new TextBlock { Text = "Welcome to DicodePing", FontSize = 26, FontWeight = FontWeight.SemiBold, TextWrapping = TextWrapping.Wrap },
            new TextBlock { Text = "زبان و ظاهر · Language & appearance", TextWrapping = TextWrapping.Wrap },
            new TextBlock { Text = "Language · زبان" }, language,
            new TextBlock { Text = "Appearance · ظاهر" }, theme
        } };
        var footer = new StackPanel { Margin = new Thickness(28, 8, 28, 20), Spacing = 8, Children = { error, next } };
        Grid.SetRow(footer, 1);
        Content = new Grid { RowDefinitions = new RowDefinitions("*,Auto"), Children = {
            new ScrollViewer { HorizontalScrollBarVisibility = Avalonia.Controls.Primitives.ScrollBarVisibility.Disabled, Content = form }, footer
        } };
    }
}
