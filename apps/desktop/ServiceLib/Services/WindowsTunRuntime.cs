namespace ServiceLib.Services;

public static class WindowsTunRuntime
{
    public static string InterfaceName => "DicodePing_" + Environment.ProcessId;
    public static bool IsMissingInterfaceFailure(string message) =>
        message.Contains("configure tun interface", StringComparison.OrdinalIgnoreCase)
        && (message.Contains("cannot find the file", StringComparison.OrdinalIgnoreCase)
            || message.Contains("file specified", StringComparison.OrdinalIgnoreCase));

    public static bool PrepareRetry(string configPath)
    {
        var root = JsonNode.Parse(File.ReadAllText(configPath))?.AsObject();
        var tun = (root?["inbounds"] as JsonArray)?.OfType<JsonObject>().FirstOrDefault(i => i["type"]?.ToString() == "tun");
        if (tun?["interface_name"]?.ToString().StartsWith("DicodePing_", StringComparison.Ordinal) != true) return false;
        tun["interface_name"] = InterfaceName + "_" + Guid.NewGuid().ToString("N")[..6];
        File.WriteAllText(configPath, root!.ToJsonString());
        return true;
    }
    public static void StageDriver(string executable, string workingDirectory)
    {
        var source = Utils.GetBinPath("wintun.dll", ECoreType.Xray.ToString());
        if (!File.Exists(source)) throw new FileNotFoundException("The signed Wintun driver is missing. Install the complete DicodePing package.", source);
        foreach (var folder in new[] { Path.GetDirectoryName(executable)!, workingDirectory }) {
            var destination = Path.Combine(folder, "wintun.dll");
            if (Path.GetFullPath(source) == Path.GetFullPath(destination)) continue;
            if (!File.Exists(destination) || !SHA256.HashData(File.ReadAllBytes(source)).SequenceEqual(SHA256.HashData(File.ReadAllBytes(destination))))
                File.Copy(source, destination, true);
        }
    }
}
