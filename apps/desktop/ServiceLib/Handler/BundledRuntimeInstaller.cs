namespace ServiceLib.Handler;

public static class BundledRuntimeInstaller
{
    public static async Task InstallAsync(string source, string destination, string version)
    {
        if (!Directory.Exists(source) || Path.GetFullPath(source) == Path.GetFullPath(destination)) return;
        Directory.CreateDirectory(destination);
        var marker = Path.Combine(destination, ".bundle-version");
        var upgrade = !File.Exists(marker) || await File.ReadAllTextAsync(marker) != version;
        FileUtils.CopyDirectory(source, destination, true, upgrade);
        if (upgrade) await File.WriteAllTextAsync(marker, version);
    }
}
