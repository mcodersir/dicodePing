using Avalonia.Layout;
using v2rayN.Desktop.ViewModels;

namespace v2rayN.Desktop.Common;

internal static class GlassAppearance
{
    private const string Glass = "glass";
    private const string Classic = "classic";

    internal static bool IsEnabled => AppManager.Instance.Config?.UiItem?.AppearanceStyle == Glass;

    internal static async Task<bool> SaveAsync(bool enabled)
    {
        var config = AppManager.Instance.Config;
        var previous = config.UiItem.AppearanceStyle;
        config.UiItem.AppearanceStyle = enabled ? Glass : Classic;
        if (await ConfigHandler.SaveConfig(config) != 0)
        {
            config.UiItem.AppearanceStyle = previous;
            return false;
        }
        ThemeSettingViewModel.RefreshAppearance();
        return true;
    }

    internal static async Task PromptAsync(Window owner)
    {
        var title = new TextBlock
        {
            Text = ResUI.DicodeGlassPromptTitle, FontSize = 22,
            FontWeight = FontWeight.SemiBold, TextWrapping = TextWrapping.Wrap,
        };
        var description = new TextBlock { Text = ResUI.DicodeGlassPromptBody, TextWrapping = TextWrapping.Wrap };
        var accept = new Button { Content = ResUI.DicodeGlassTry, MinHeight = 44, HorizontalAlignment = HorizontalAlignment.Stretch };
        var decline = new Button { Content = ResUI.DicodeStyleClassic, IsCancel = true, MinHeight = 44, HorizontalAlignment = HorizontalAlignment.Stretch };
        var dialog = new Window
        {
            Title = ResUI.DicodeInterfaceStyle,
            Width = Math.Clamp(owner.Bounds.Width, 300, 460),
            SizeToContent = SizeToContent.Height,
            CanResize = false,
            ShowInTaskbar = false,
            WindowStartupLocation = WindowStartupLocation.CenterOwner,
            FlowDirection = owner.FlowDirection,
            Content = new StackPanel { Margin = new Thickness(24), Spacing = 12,
                Children = { title, description, accept, decline } },
        };
        accept.Click += (_, _) => dialog.Close(true);
        decline.Click += (_, _) => dialog.Close(false);
        var chosen = await dialog.ShowDialog<bool>(owner);
        if (!await SaveAsync(chosen))
            NoticeManager.Instance.Enqueue(ResUI.DicodeAppearanceSaveFailed);
    }
}
