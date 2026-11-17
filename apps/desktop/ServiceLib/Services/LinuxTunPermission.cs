namespace ServiceLib.Services;

public static class LinuxTunPermission
{
    public static bool HasConfiguredCapabilities(Config config)
    {
        if (!OperatingSystem.IsLinux()) return false;
        try
        {
            var type = config.TunModeItem.EnableLegacyProtect ? ECoreType.sing_box : ECoreType.Xray;
            var info = CoreInfoManager.Instance.GetCoreInfo(type);
            var executable = CoreInfoManager.Instance.GetCoreExecFile(info, out _);
            return HasCapabilities(executable);
        }
        catch { return false; }
    }

    public static bool HasCapabilities(string executable)
    {
        if (!OperatingSystem.IsLinux() || !File.Exists(executable)) return false;
        try
        {
            using var process = new Process { StartInfo = new ProcessStartInfo("getcap") {
                UseShellExecute = false, RedirectStandardOutput = true, RedirectStandardError = true,
                ArgumentList = { executable }
            } };
            process.Start();
            if (!process.WaitForExit(1500)) { process.Kill(); return false; }
            var output = process.StandardOutput.ReadToEnd();
            return process.ExitCode == 0 && output.Contains("cap_net_admin") && output.Contains("cap_net_raw")
                && (output.Contains("=ep") || output.Contains("=eip"));
        }
        catch { return false; }
    }
}
