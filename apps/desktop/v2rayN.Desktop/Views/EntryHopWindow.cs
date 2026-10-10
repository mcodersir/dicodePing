using ServiceLib.Services;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Layout;
using v2rayN.Desktop.Base;

namespace v2rayN.Desktop.Views;

public sealed class EntryHopWindow : Window
{
    public EntryHopWindow(MainWindowViewModel main)
    {
        var config = AppManager.Instance.Config;
        var item = config.EntryHopItem;
        Title = ResUI.DicodeEntryTitle; Width = 620; Height = 560; MinWidth = 400;
        WindowStartupLocation = WindowStartupLocation.CenterOwner;
        var enabled = new CheckBox { Content = ResUI.DicodeEntryEnable, IsChecked = item.Enabled };
        var kinds = new[] { "aether", "psiphon", "aether-psiphon", "aether-tor", "external" };
        var kind = new ComboBox { ItemsSource = new[] { "Aether", "Psiphon", "Aether → Psiphon", "Aether → Tor", ResUI.DicodeEntryExternal }, SelectedIndex = Math.Max(0, Array.IndexOf(kinds, item.Kind)), HorizontalAlignment = HorizontalAlignment.Stretch };
        var scope = new ComboBox { ItemsSource = new[] { ResUI.DicodeEntryProfile, ResUI.DicodeEntrySubscription, ResUI.DicodeEntryAll }, SelectedIndex = item.ProfileId.IsNotEmpty() ? 0 : item.SubscriptionId.IsNotEmpty() ? 1 : 2, HorizontalAlignment = HorizontalAlignment.Stretch };
        var policy = new ComboBox { ItemsSource = new[] { ResUI.DicodeEntryFirst, ResUI.DicodeEntryBest }, SelectedIndex = item.Policy == "best" ? 1 : 0, HorizontalAlignment = HorizontalAlignment.Stretch };
        var port = new TextBox { Text = item.Port.ToString(), PlaceholderText = "61080" };
        var status = new TextBlock { Text = item.LastTransport, TextWrapping = Avalonia.Media.TextWrapping.Wrap };
        var save = new Button { Content = ResUI.TbConfirm, HorizontalAlignment = HorizontalAlignment.Stretch };
        var scan = new Button { Content = ResUI.DicodeEntryRescan, HorizontalAlignment = HorizontalAlignment.Stretch };
        bool Save()
        {
            if (!int.TryParse(port.Text, out var parsed) || parsed is < 1024 or > 65535) { status.Text = ResUI.DicodeEntryPortBusy; return false; }
            var profileId = scope.SelectedIndex == 0 ? main.ProfilesViewModel.SelectedProfile?.IndexId : "";
            var subscriptionId = scope.SelectedIndex == 1 ? main.ProfilesViewModel.SelectedSub?.Id : "";
            if ((scope.SelectedIndex == 0 && profileId.IsNullOrEmpty()) || (scope.SelectedIndex == 1 && subscriptionId.IsNullOrEmpty()))
            { status.Text = ResUI.PleaseSelectServer; return false; }
            item.Enabled = enabled.IsChecked == true; item.Kind = kinds[kind.SelectedIndex];
            item.ProfileId = profileId ?? ""; item.SubscriptionId = subscriptionId ?? "";
            item.Port = parsed; item.Policy = policy.SelectedIndex == 1 ? "best" : "first";
            return true;
        }
        save.Click += async (_, _) => { if (!Save()) return; await ConfigHandler.SaveConfig(config); Close(); };
        scan.Click += async (_, _) =>
        {
            if (!Save()) return;
            scan.IsEnabled = false; save.IsEnabled = false;
            using var cts = new CancellationTokenSource(TimeSpan.FromMinutes(3));
            try
            {
                await main.ProfilesViewModel.StopDiagnosticsAsync();
                await CoreManager.Instance.CoreStop();
                status.Text = ResUI.DicodeProbeRunning;
                await Task.Run(() => EntryHopService.EnsureReadyAsync(config, true, cts.Token));
                status.Text = ResUI.DicodeEntryReady + " · " + item.LastTransport;
            }
            catch (Exception ex) { Logging.SaveLog("Entry-hop scan", ex); status.Text = ResUI.DicodeEntryFailed; }
            finally { scan.IsEnabled = true; save.IsEnabled = true; }
        };
        Content = new ScrollViewer { Content = new StackPanel { Margin = new Thickness(24), Spacing = 14, Children = {
            new TextBlock { Text = ResUI.DicodeEntryTitle, FontSize = 24 },
            new TextBlock { Text = ResUI.DicodeEntryHint, TextWrapping = Avalonia.Media.TextWrapping.Wrap },
            enabled, kind, scope, policy, new TextBlock { Text = ResUI.DicodeEntryPort }, port, status, scan, save
        } } };
    }
}
