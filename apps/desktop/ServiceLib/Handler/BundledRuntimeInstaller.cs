namespace ServiceLib.Handler;

public static class BundledRuntimeInstaller
{
    public static async Task InstallAsync(string source, string destination, string version)
    {
        if (!Directory.Exists(source) || Path.GetFullPath(source) == Path.GetFullPath(destination)) return;
        Directory.CreateDirectory(destination);
        var marker = Path.Combine(destination, ".bundle-version");
        var upgrade = !File.Exists(marker) || await File.ReadAllTextAsync(marker) != version;
        foreach (var file in Directory.EnumerateFiles(source, "*", SearchOption.AllDirectories))
        {
            var target = Path.Combine(destination, Path.GetRelativePath(source, file));
            // Unchanged executables retain their inode, ownership and Linux capabilities.
            if (File.Exists(target))
            {
                if (!upgrade) continue;
                var sourceHash = System.Security.Cryptography.SHA256.HashData(await File.ReadAllBytesAsync(file));
                var targetHash = System.Security.Cryptography.SHA256.HashData(await File.ReadAllBytesAsync(target));
                if (sourceHash.SequenceEqual(targetHash)) continue;
            }
            Directory.CreateDirectory(Path.GetDirectoryName(target)!);
            try { File.Copy(file, target, true); }
            catch (UnauthorizedAccessException error)
            {
                throw new UnauthorizedAccessException($"Cannot update runtime {target}. A previous sudo launch may have created root-owned data. Run the GUI as your normal user and see LINUX-TUN.md to restore ownership.", error);
            }
            if (!OperatingSystem.IsWindows()) File.SetUnixFileMode(target, File.GetUnixFileMode(file));
        }
        if (upgrade) await File.WriteAllTextAsync(marker, version);
    }
}
