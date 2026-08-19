using v2rayN.Desktop.Common;
using v2rayN.Desktop.Manager;

namespace v2rayN.Desktop;

internal class Program
{
    public static EventWaitHandle ProgramStarted;

    // Initialization code. Don't use any Avalonia, third-party APIs or any
    // SynchronizationContext-reliant code before AppMain is called: things aren't initialized
    // yet and stuff might break.
    [STAThread]
    public static void Main(string[] args)
    {
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

        // A TUN adapter changes routing tables on Linux and macOS, so DicodePing deliberately
        // refuses to start without an elevated desktop session on those platforms as well.
        if (Environment.UserName.Equals("root", StringComparison.OrdinalIgnoreCase))
        {
            return true;
        }

        Console.Error.WriteLine("DicodePing must be launched with administrator privileges (sudo).");
        return false;
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
            _ = new Mutex(true, "DicodePing.Desktop", out var bOnlyOneInstance);
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
