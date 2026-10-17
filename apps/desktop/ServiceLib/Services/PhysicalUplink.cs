namespace ServiceLib.Services;

/// <summary>Finds a usable hardware uplink without changing another VPN's adapters or routes.</summary>
public static class PhysicalUplink
{
    public static bool IsCandidate(string name, string description, NetworkInterfaceType type, OperationalStatus status, bool hasGateway) =>
        status == OperationalStatus.Up && hasGateway
        && type is NetworkInterfaceType.Ethernet or NetworkInterfaceType.Wireless80211
        && !new[] { "warp", "wireguard", "wintun", "tun", "tap", "vpn", "virtual", "hyper-v", "vethernet", "tailscale", "zerotier" }
            .Any(word => (name + " " + description).Contains(word, StringComparison.OrdinalIgnoreCase));

    public static string? Find()
    {
        if (!OperatingSystem.IsWindows()) return null;
        try {
            var candidates = NetworkInterface.GetAllNetworkInterfaces().Where(n =>
                IsCandidate(n.Name, n.Description, n.NetworkInterfaceType, n.OperationalStatus,
                    n.GetIPProperties().GatewayAddresses.Any(g => g.Address.AddressFamily == AddressFamily.InterNetwork
                        && !g.Address.Equals(IPAddress.Any)))).ToList();
            if (candidates.Count == 0) return null;
            // Prefer the lowest combined default-route + interface metric, considering hardware adapters only.
            using var process = new Process { StartInfo = new ProcessStartInfo("powershell.exe") {
                UseShellExecute = false, CreateNoWindow = true, RedirectStandardOutput = true, RedirectStandardError = true,
                ArgumentList = { "-NoProfile", "-NonInteractive", "-Command",
                    "Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue | Sort-Object @{Expression={$_.RouteMetric + $_.InterfaceMetric}} | ForEach-Object {$_.InterfaceIndex}" }
            }};
            process.Start();
            var output = process.StandardOutput.ReadToEndAsync();
            if (!process.WaitForExit(3000)) { process.Kill(); return null; }
            foreach (var line in output.GetAwaiter().GetResult().Split('\n'))
                if (int.TryParse(line.Trim(), out var index) && candidates.FirstOrDefault(n => n.GetIPProperties().GetIPv4Properties()?.Index == index) is { } match)
                    return match.Name;
            return null;
        } catch (Exception ex) { Logging.SaveLog("Physical uplink detection", ex); return null; }
    }
}
