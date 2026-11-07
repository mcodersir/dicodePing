using System.IO.Compression;

namespace AmazTool;

/// <summary>Validates portable release paths before touching an installed file.</summary>
public static class UpdateArchive
{
    public static IReadOnlyList<(ZipArchiveEntry Entry, string Target)> Plan(ZipArchive archive, string directory)
    {
        var installDirectory = Path.TrimEndingDirectorySeparator(Path.GetFullPath(directory));
        var entries = archive.Entries.Where(e => !e.FullName.EndsWith('/') && e.Length > 0).ToList();
        var launcher = entries.FirstOrDefault(e => e.FullName is "DicodePing.exe" or "DicodePing")
            ?? entries.FirstOrDefault(e => e.FullName.EndsWith("/DicodePing.exe", StringComparison.Ordinal) || e.FullName.EndsWith("/DicodePing", StringComparison.Ordinal))
            ?? throw new InvalidDataException("The update has no DicodePing launcher.");
        var prefix = launcher.FullName[..(launcher.FullName.LastIndexOf('/') + 1)];
        var appBundle = prefix.EndsWith(".app/Contents/MacOS/", StringComparison.Ordinal);
        if (appBundle)
        {
            var macos = new DirectoryInfo(installDirectory);
            if (macos.Name != "MacOS" || macos.Parent?.Name != "Contents" || macos.Parent.Parent?.Name.EndsWith(".app", StringComparison.Ordinal) != true)
                throw new InvalidDataException("The macOS updater must run inside its application bundle.");
            installDirectory = macos.Parent.Parent.FullName;
            prefix = prefix[..^"Contents/MacOS/".Length];
        }
        var root = installDirectory + Path.DirectorySeparatorChar;

        List<(ZipArchiveEntry, string)> result = [];
        var names = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var entry in entries)
        {
            if (!entry.FullName.StartsWith(prefix, StringComparison.Ordinal))
            {
                if (appBundle && entry.FullName == "README.txt") continue;
                throw new InvalidDataException("Mixed update roots.");
            }
            var name = entry.FullName[prefix.Length..];
            if (name.Contains('\\') || name.StartsWith('/') || name.Split('/').Any(s => s is "." or ".." || s.Contains(':'))
                || ((entry.ExternalAttributes >> 16) & 0xF000) == 0xA000)
                throw new InvalidDataException("Unsafe update path.");
            var target = Path.GetFullPath(Path.Combine(root, name));
            if (!target.StartsWith(root, StringComparison.Ordinal) || !names.Add(target)) throw new InvalidDataException("Duplicate or invalid update path.");
            // User data is never part of a binary replacement.
            if (name.Split('/').Any(part => part is "guiConfigs" or "guiLogs" or "guiTemps" or "config.json")) continue;
            result.Add((entry, target));
        }
        return result;
    }
}
