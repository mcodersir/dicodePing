namespace ServiceLib.Handler;

public static class BundledRuntimeInstaller
{
    public static async Task InstallAsync(string source, string destination, string version)
    {
        // Remove only the retired runtime directory owned by this application.
        foreach (var root in new[] { source, destination }.Distinct()) {
            var retired = Path.Combine(root, "sing_box");
            try { if (Directory.Exists(retired)) Directory.Delete(retired, true); }
            catch (Exception error) { Logging.SaveLog("Retired runtime cleanup", error); }
        }
        if (!Directory.Exists(source) || Path.GetFullPath(source) == Path.GetFullPath(destination)) return;
        Directory.CreateDirectory(destination);
        var marker = Path.Combine(destination, ".bundle-version");
        var upgrade = !File.Exists(marker) || await File.ReadAllTextAsync(marker) != version;
        FileUtils.CopyDirectory(source, destination, true, upgrade);
        if (upgrade) await File.WriteAllTextAsync(marker, version);
    }
}
