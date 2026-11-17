using v2rayN.Desktop.Common;
using v2rayN.Desktop.Manager;

namespace v2rayN.Desktop;

internal class Program
{
    public static EventWaitHandle ProgramStarted;
    private static Mutex? _instanceMutex;

    // Initialization code. Don't use any Avalonia, third-party APIs or any
    // SynchronizationContext-reliant code before AppMain is called: things aren't initialized
    // yet and stuff might break.
    [STAThread]
    public static void Main(string[] args)
    {
        // Avalonia's embedded WebKitGTK host uses X11. Select the same GTK
        // backend before either toolkit initializes in a KDE Wayland session.
        if (OperatingSystem.IsLinux() && !string.IsNullOrEmpty(Environment.GetEnvironmentVariable("DISPLAY")))
        {
            Environment.SetEnvironmentVariable("GDK_BACKEND", "x11");
            // The sign-in view does not need compositing. Avoid native WebKit
            // renderer crashes with XWayland/software-only display drivers.
            if (string.IsNullOrEmpty(Environment.GetEnvironmentVariable("WEBKIT_DISABLE_COMPOSITING_MODE")))
                Environment.SetEnvironmentVariable("WEBKIT_DISABLE_COMPOSITING_MODE", "1");
            if (!string.IsNullOrEmpty(Environment.GetEnvironmentVariable("WAYLAND_DISPLAY"))
                && string.IsNullOrEmpty(Environment.GetEnvironmentVariable("WEBKIT_DISABLE_DMABUF_RENDERER")))
                Environment.SetEnvironmentVariable("WEBKIT_DISABLE_DMABUF_RENDERER", "1");
        }
        if (!RequireAdministrator())
        {
            Environment.Exit(0);
            return;
        }

        if (OnStartup(args) == false)
        {
            Environment.Exit(0);
            return;
        }

        BuildAvaloniaApp()
            .StartWithClassicDesktopLifetime(args);
    }

    private static bool RequireAdministrator()
    {
        if (Utils.IsWindows())
        {
            if (Utils.IsAdministrator())
            {
                return true;
            }

            // Windows is elevated through the embedded requireAdministrator manifest. This
            // fallback also covers direct launches of an unpacked development binary.
            return ProcUtils.RebootAsAdmin();
        }

        // Opening a desktop window never requires root. TUN elevation is checked
        // when starting a tunnel, not before the UI or reports can be opened.
        Environment.SetEnvironmentVariable(Global.LocalAppData, "1");
        return true;
    }

    private static bool OnStartup(string[]? Args)
    {
        if (Utils.IsWindows())
        {
            var exePathKey = Utils.GetMd5(Utils.GetExePath());
            var rebootas = (Args ?? []).Any(t => t == Global.RebootAs);
            ProgramStarted = new EventWaitHandle(false, EventResetMode.AutoReset, exePathKey, out var bCreatedNew);
            if (!rebootas && !bCreatedNew)
            {
                ProgramStarted.Set();
                return false;
            }
        }
        else
        {
            // Retain the mutex for the entire process, including when the window is in the tray.
            _instanceMutex = new Mutex(true, "DicodePing.Desktop", out var bOnlyOneInstance);
            if (!bOnlyOneInstance)
            {
                return false;
            }
        }

        if (!AppManager.Instance.InitApp())
        {
            return false;
        }

        AppManager.Instance.WindowDialog = new WindowDialog();
        return true;
    }

    // Avalonia configuration, don't remove; also used by visual designer.
    public static AppBuilder BuildAvaloniaApp()
    {
        var builder = AppBuilder.Configure<App>()
           .UsePlatformDetect()
           //.WithInterFont()
           .WithFontByDefault()
#if DEBUG
           .WithDeveloperTools()
#endif
           .LogToTrace()
           .UseReactiveUI(_ => { });

        if (OperatingSystem.IsMacOS())
        {
            var showInDock = Design.IsDesignMode || AppManager.Instance.Config.UiItem.MacOSShowInDock;
            builder = builder.With(new MacOSPlatformOptions { ShowInDock = showInDock });
        }

        return builder;
    }
}
