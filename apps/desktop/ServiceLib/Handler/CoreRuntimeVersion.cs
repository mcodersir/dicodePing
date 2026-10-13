namespace ServiceLib.Handler;

public static class CoreRuntimeVersion
{
    public static SemanticVersion Parse(ECoreType type, string? output)
    {
        var pattern = type switch
        {
            ECoreType.mihomo => @"(?i)mihomo(?:\s+meta)?\s+v?(\d+\.\d+\.\d+(?:-[\w.]+)?)",
            ECoreType.sing_box => @"(?i)sing-box\s+version\s+v?(\d+\.\d+\.\d+(?:-[\w.]+)?)",
            _ => @"(?i)(?:xray|v2ray)\s+v?(\d+\.\d+\.\d+(?:-[\w.]+)?)"
        };
        return new SemanticVersion(Regex.Match(output ?? string.Empty, pattern).Groups[1].Value);
    }
}
