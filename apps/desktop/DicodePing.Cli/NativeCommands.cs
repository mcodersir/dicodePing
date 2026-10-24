using System.Diagnostics;
using System.Text.Json;
using ServiceLib.Services;

internal static class NativeCommands
{
    public static async Task<int> Execute(string[] args, string engine, CancellationToken token)
    {
        if (args.Length < 2) throw new ArgumentException(CliText.T("مسیر فایل پیکربندی لازم است", "A configuration file is required"));
        var file = Path.GetFullPath(args[1]);
        if (!File.Exists(file)) throw new FileNotFoundException(CliText.T("فایل پیکربندی پیدا نشد", "Configuration file not found"));
        var binary = engine switch { "xray" => "xray/xray", "mihomo" => "mihomo/mihomo", _ => throw new ArgumentException(CliText.T("هسته انتخاب‌شده پشتیبانی نمی‌شود", "Unsupported native engine")) };
        var path = Path.Combine(AppContext.BaseDirectory, "bin", binary + (OperatingSystem.IsWindows() ? ".exe" : ""));
        if (!File.Exists(path)) throw new FileNotFoundException(CliText.T("هسته همراه برنامه پیدا نشد", "Bundled core is missing"), path);
        var start = new ProcessStartInfo(path) { UseShellExecute = false, RedirectStandardOutput = true, RedirectStandardError = true, WorkingDirectory = Path.Combine(AppContext.BaseDirectory, "bin") };
        foreach (var name in new[] { "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy" }) start.Environment.Remove(name);
        string[] command = engine switch {
            "xray" => args[0] == "check" ? ["run", "-test", "-c", file] : ["run", "-c", file],
            _ => args[0] == "check" ? ["-t", "-f", file] : ["-f", file]
        };
        foreach (var word in command) start.ArgumentList.Add(word);
        using var process = Process.Start(start) ?? throw new IOException(CliText.T("هسته اجرا نشد", "Cannot start native core"));
        var stdout = Forward(process.StandardOutput, Console.Out);
        var stderr = Forward(process.StandardError, Console.Error);
        try { await process.WaitForExitAsync(token); await Task.WhenAll(stdout, stderr); return process.ExitCode; }
        finally { if (!process.HasExited) { process.Kill(entireProcessTree: true); await process.WaitForExitAsync(); } }
    }
    private static async Task Forward(StreamReader from, TextWriter to) { while (await from.ReadLineAsync() is { } line) await to.WriteLineAsync(line); }
    public static async Task<int> Scan(string[] args, CancellationToken token)
    {
        if (args.Length < 2) throw new ArgumentException(CliText.T("فرمان scan-cf به فایل فهرست IP نیاز دارد", "scan-cf requires an IP list file"));
        var results = await CloudflareScanner.ScanAsync(await File.ReadAllLinesAsync(args[1], token), (done, total) => Console.Error.WriteLine($"{done}/{total}"), token);
        Console.WriteLine(JsonSerializer.Serialize(results, new JsonSerializerOptions { WriteIndented = true }));
        return results.Any(x => x.Latency.HasValue) ? 0 : 2;
    }
}
