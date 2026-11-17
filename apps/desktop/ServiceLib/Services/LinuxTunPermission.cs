namespace ServiceLib.Services;

public static class LinuxTunPermission
{
    public static async Task<bool> HasConfiguredCapabilitiesAsync(Config config)
    {
        if (!OperatingSystem.IsLinux()) return false;
        try
        {
            var node = await AppManager.Instance.GetProfileItem(config.IndexId);
            if (node is null) return false;
            var type = AppManager.Instance.GetCoreType(node, node.ConfigType);
            if (ConfigHandler.GetPreSocksItem(config, node, type) is not null) type = ECoreType.sing_box;
            var info = CoreInfoManager.Instance.GetCoreInfo(type);
            var executable = CoreInfoManager.Instance.GetCoreExecFile(info, out _);
            return await Task.Run(() => HasCapabilities(executable));
        }
        catch { return false; }
    }

    public static bool HasCapabilities(string executable)
    {
        if (!OperatingSystem.IsLinux() || !File.Exists(executable)) return false;
        try
        {
            var getcap = new[] { "/usr/sbin/getcap", "/sbin/getcap" }.FirstOrDefault(File.Exists) ?? "getcap";
            using var process = new Process { StartInfo = new ProcessStartInfo(getcap) {
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
