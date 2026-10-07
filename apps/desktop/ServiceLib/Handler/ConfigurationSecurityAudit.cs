namespace ServiceLib.Handler;

/// <summary>Static configuration audit, independent from network reachability and latency.</summary>
public static class ConfigurationSecurityAudit
{
    public static string Describe(ProfileItem profile)
    {
        if (profile.GetAllowInsecure()) return ResUI.DicodeSecurityHighRiskInsecure;
        if (string.Equals(profile.StreamSecurity, "tls", StringComparison.OrdinalIgnoreCase)
            || string.Equals(profile.StreamSecurity, "reality", StringComparison.OrdinalIgnoreCase))
            return string.Format(ResUI.DicodeSecuritySecure, profile.StreamSecurity.ToUpperInvariant());
        if (profile.ConfigType is EConfigType.SOCKS or EConfigType.HTTP or EConfigType.VLESS or EConfigType.Trojan)
            return ResUI.DicodeSecurityHighRiskPlain;
        return ResUI.DicodeSecurityMediumNoTls;
    }
}
