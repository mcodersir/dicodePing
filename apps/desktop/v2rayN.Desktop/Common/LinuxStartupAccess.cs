using System.Diagnostics;
using System.Runtime.InteropServices;

namespace v2rayN.Desktop.Common;

internal static class LinuxStartupAccess
{
    [DllImport("libc")]
    private static extern uint geteuid();

    public static bool CanStart()
    {
        if (geteuid() == 0)
            return Report("DicodePing باید با حساب عادی اجرا شود. دسترسی TUN را در خود برنامه تنظیم کنید.");

        var directory = Utils.StartupPath();
        if (!Directory.Exists(directory)) return true;

        // The physical walk does not follow symlinks or traverse other mounted filesystems.
        try
        {
            using var find = Process.Start(new ProcessStartInfo("/usr/bin/find")
            {
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                ArgumentList = { "-P", directory, "-xdev", "-uid", "0", "-print0", "-quit" }
            });
            if (find is null) return true;
            var output = find.StandardOutput.ReadToEndAsync();
            _ = find.StandardError.ReadToEndAsync();
            if (!find.WaitForExit(1200))
            {
                find.Kill();
                return true;
            }
            if (output.GetAwaiter().GetResult().Length > 0)
                return Report($"بخشی از داده‌های DicodePing متعلق به root است. مالکیت فایل‌ها را طبق راهنمای LINUX-TUN.md برگردانید و برنامه را با حساب عادی باز کنید.\n{directory}");
        }
        catch (System.ComponentModel.Win32Exception) { }
        catch (InvalidOperationException) { }
        return true;
    }

    private static bool Report(string message)
    {
        Console.Error.WriteLine(message);
        foreach (var (command, option) in new[] { ("/usr/bin/kdialog", "--error"), ("/usr/bin/zenity", "--error") })
        {
            if (!File.Exists(command)) continue;
            try
            {
                using var dialog = Process.Start(new ProcessStartInfo(command)
                {
                    ArgumentList = { option, command.EndsWith("zenity") ? "--text=" + message : message }
                });
                break;
            }
            catch (System.ComponentModel.Win32Exception) { }
        }
        return false;
    }
}
