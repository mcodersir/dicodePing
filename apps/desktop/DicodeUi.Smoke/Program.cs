using ReactiveUI.Avalonia;
using v2rayN.Desktop.Common;
using Avalonia.VisualTree;
using System.Globalization;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Headless;
using Avalonia.Media.Imaging;
using Avalonia.Styling;
using ServiceLib.Manager;
using ServiceLib.Models;
using ServiceLib.Models.Configs;
using ServiceLib.Models.Dto;
using ServiceLib.Enums;
using System.Reflection;
using v2rayN.Desktop.Views;

AppBuilder.Configure<v2rayN.Desktop.App>().WithFontByDefault().UseSkia()
    .UseHeadless(new AvaloniaHeadlessPlatformOptions { UseHeadlessDrawing = false })
    .UseReactiveUI(_ => { }).SetupWithoutStarting();
typeof(AppManager).GetField("_config", BindingFlags.Instance | BindingFlags.NonPublic)!
    .SetValue(AppManager.Instance, new Config { UiItem = new UIItem() });
Directory.CreateDirectory("desktop-qa");
foreach (var width in new[] { 480, 800, 1180 })
foreach (var rtl in new[] { false, true })
foreach (var dark in new[] { false, true })
{
    Application.Current!.RequestedThemeVariant = dark ? ThemeVariant.Dark : ThemeVariant.Light;
    ServiceLib.Resx.ResUI.Culture = new CultureInfo(rtl ? "fa-IR" : "en-US");
    typeof(v2rayN.Desktop.ViewModels.ThemeSettingViewModel).GetMethod("ApplyDicodePalette", BindingFlags.Static | BindingFlags.NonPublic)!
        .Invoke(null, new object[] { Application.Current, dark ? "Dark" : "Light", dark });
    var view = new ProfilesView { Width = width, Height = 720,
        FlowDirection = rtl ? Avalonia.Media.FlowDirection.RightToLeft : Avalonia.Media.FlowDirection.LeftToRight };
    var list = view.FindControl<ListBox>("lstProfiles")!;
    view.FindControl<Border>("emptyProfiles")!.IsVisible = false;
    list.ItemsSource = new[] {
        new ProfileItemModel { RowNumber = 1, Remarks = "Germany · مسیر آلمان", Address = "edge.example.net", ConfigType = EConfigType.VLESS, IpInfo = "DE 203.0.113.1", DelayVal = "42 ms", SpeedVal = "18.6 MB/s", SecurityInfo = "TLS", SanctionsInfo = "5/5", IsActive = true },
        new ProfileItemModel { RowNumber = 2, Remarks = "Finland · یک نام بسیار طولانی برای بررسی چیدمان و جلوگیری از بیرون‌زدگی ردیف", Address = "long-address-for-layout-check.example.net", ConfigType = EConfigType.Trojan, IpInfo = "FI 203.0.113.2", DelayVal = "76 ms", SpeedVal = "12.4 MB/s", SecurityInfo = "TLS", IsSanctionsTesting = true },
        new ProfileItemModel { RowNumber = 3, Remarks = "Unknown location", Address = "example.net", ConfigType = EConfigType.VLESS, IsLocationTesting = true, IsLatencyTesting = true }
    };
    var window = new Window { Width = width, Height = 720, Content = view };
    window.Show();
    view.Measure(new Size(width, 720)); view.Arrange(new Rect(0, 0, width, 720));
    Avalonia.Threading.Dispatcher.UIThread.RunJobs();
    if (list.GetVisualDescendants().OfType<ListBoxItem>().Count() != 3) throw new Exception("Profile rows were not realized");
    using var bitmap = new RenderTargetBitmap(new PixelSize(width, 720));
    bitmap.Render(view);
    bitmap.Save($"desktop-qa/profiles-{width}-{(rtl ? "rtl" : "ltr")}-{(dark ? "dark" : "light")}.png");
    window.Close();
    Console.WriteLine($"Rendered profile list {width}px / {(rtl ? "rtl" : "ltr")} / {(dark ? "dark" : "light")}");
}
