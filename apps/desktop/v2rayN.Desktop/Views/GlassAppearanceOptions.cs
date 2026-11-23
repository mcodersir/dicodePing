using Avalonia.Layout;
using v2rayN.Desktop.Common;

namespace v2rayN.Desktop.Views;

public sealed class GlassAppearanceOptions : UserControl
{
    public GlassAppearanceOptions()
    {
        var picker = new ComboBox
        {
            ItemsSource = new[] { ResUI.DicodeStyleClassic, ResUI.DicodeStyleGlass },
            HorizontalAlignment = HorizontalAlignment.Stretch,
            MinHeight = 44,
        };
        Avalonia.Automation.AutomationProperties.SetName(picker, ResUI.DicodeInterfaceStyle);
        var error = new TextBlock { TextWrapping = TextWrapping.Wrap };
        var synchronizing = false;
        void Refresh()
        {
            synchronizing = true;
            picker.SelectedIndex = GlassAppearance.IsEnabled ? 1 : 0;
            synchronizing = false;
        }
        AttachedToVisualTree += (_, _) => Refresh();
        picker.DropDownOpened += (_, _) => Refresh();
        picker.SelectionChanged += async (_, _) =>
        {
            if (synchronizing || picker.SelectedIndex is < 0 or > 1) return;
            picker.IsEnabled = false;
            error.Text = await GlassAppearance.SaveAsync(picker.SelectedIndex == 1)
                ? "" : ResUI.DicodeAppearanceSaveFailed;
            Refresh();
            picker.IsEnabled = true;
        };
        var card = new Border
        {
            MaxWidth = 520, HorizontalAlignment = HorizontalAlignment.Stretch,
            Padding = new Thickness(20), Margin = new Thickness(8),
            Child = new StackPanel { Spacing = 12, Children =
            {
                new TextBlock { Text = ResUI.DicodeInterfaceStyle, FontWeight = FontWeight.SemiBold, FontSize = 19 },
                new TextBlock { Text = ResUI.DicodeGlassPromptBody, TextWrapping = TextWrapping.Wrap },
                picker, error,
            } },
        };
        card.Classes.Add("DicodeCard");
        Content = new ScrollViewer { Content = card };
    }
}
