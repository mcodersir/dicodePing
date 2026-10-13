using System.Diagnostics;

namespace ServiceLib.Services;

public static class NativeConfigurationValidator
{
    public static async Task ValidateAsync(string file, CancellationToken token = default)
    {
        var binary = CoreInfoManager.Instance.GetCoreExecFile(CoreInfoManager.Instance.GetCoreInfo(ECoreType.sing_box), out var error);
        if (binary.IsNullOrEmpty()) throw new FileNotFoundException(error);
        using var process = new Process { StartInfo = new ProcessStartInfo(binary) { UseShellExecute = false, RedirectStandardOutput = true, RedirectStandardError = true } };
        foreach (var arg in new[] { "check", "-c", Path.GetFullPath(file) }) process.StartInfo.ArgumentList.Add(arg);
        process.Start(); var stdout = process.StandardOutput.ReadToEndAsync(); var stderr = process.StandardError.ReadToEndAsync();
        using var deadline = CancellationTokenSource.CreateLinkedTokenSource(token); deadline.CancelAfter(TimeSpan.FromSeconds(10));
        try { await process.WaitForExitAsync(deadline.Token); }
        finally { if (!process.HasExited) { process.Kill(true); await process.WaitForExitAsync(); } }
        if (process.ExitCode != 0) throw new InvalidDataException((await stderr + await stdout).Trim());
    }
}
