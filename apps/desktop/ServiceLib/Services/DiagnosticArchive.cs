using System.IO.Compression;
using System.Runtime.InteropServices;
using System.Text.RegularExpressions;

namespace ServiceLib.Services;

public static class DiagnosticArchive
{
    public static string Redact(string text)
    {
        text = Regex.Replace(text, @"(?i)(""(?:access_token|refresh_token|session_token|sessionToken|authPW|password|token|authorization|private_key|privateKey|secret)""\s*:\s*)""(?:\\.|[^""\\])*""", "$1\"[redacted]\"", RegexOptions.None, TimeSpan.FromSeconds(1));
        foreach (var pattern in new[] {
            @"(?i)Bearer\s+[^\s""']+",
            @"(?i)(?:vless|vmess|trojan|ss|socks5?)://[^\s""']+",
            @"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
            @"(?i)\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b" })
            text = Regex.Replace(text, pattern, "[redacted]", RegexOptions.None, TimeSpan.FromSeconds(1));
        return Regex.Replace(text, "(?i)(\"?(?:access_token|refresh_token|session_token|sessionToken|authPW|password|token|authorization|private_key|privateKey|secret)\"?\\s*[:=]\\s*\"?)[^\"\\s,}]+", "$1[redacted]", RegexOptions.None, TimeSpan.FromSeconds(1));
    }

    public static void Write(Stream output)
    {
        using var zip = new ZipArchive(output, ZipArchiveMode.Create, leaveOpen: true);
        void Add(string name, string text) {
            using var writer = new StreamWriter(zip.CreateEntry(name, CompressionLevel.Fastest).Open(), Encoding.UTF8);
            writer.Write(Redact(text));
        }
        string interfaces;
        try { interfaces = string.Join("\n", NetworkInterface.GetAllNetworkInterfaces().Select(n => $"interface={n.Name}; type={n.NetworkInterfaceType}; status={n.OperationalStatus}")); }
        catch (Exception error) { interfaces = "interfaces unavailable: " + error.GetType().Name; }
        Add("system.txt", $"version={Utils.GetVersion()}\nos={RuntimeInformation.OSDescription}\narchitecture={RuntimeInformation.ProcessArchitecture}\nruntime={RuntimeInformation.FrameworkDescription}\ntun={AppManager.Instance.Config.TunModeItem.EnableTun}\ncore={AppManager.Instance.RunningCoreType}\n" +
            interfaces);
        foreach (var file in Directory.EnumerateFiles(Utils.GetLogPath(""), "*.txt").OrderByDescending(File.GetLastWriteTimeUtc).Take(3)) {
            using var stream = new FileStream(file, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete);
            if (stream.Length > 2 * 1024 * 1024) stream.Seek(-2 * 1024 * 1024, SeekOrigin.End);
            using var reader = new StreamReader(stream, Encoding.UTF8, true);
            Add("logs/" + Path.GetFileName(file), reader.ReadToEnd());
        }
        Add("README.txt", "Application logs and system versions only. No account vault, database, subscriptions or raw proxy configurations are included. Review before sharing.");
    }
}
