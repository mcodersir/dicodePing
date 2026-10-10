namespace ServiceLib.Handler;

public static class SniBlockPreset
{
    public const string Fragment = """{"tcp":[{"type":"fragment","settings":{"packets":"tlshello","lengths":["6","98","1"],"delays":["0"],"maxSplit":"0"}}]}""";
    public const string Ciphers = "TLS_ECDHE_ECDSA_WITH_AES_128_GCM_SHA256:TLS_ECDHE_RSA_WITH_AES_128_GCM_SHA256:TLS_ECDHE_ECDSA_WITH_AES_256_GCM_SHA384:TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384";
    public static void Apply(ProfileItem profile)
    {
        if (profile.StreamSecurity != Global.StreamSecurity) return;
        profile.Fingerprint = "unsafe";
        if (profile.CipherSuites.IsNullOrEmpty()) profile.CipherSuites = Ciphers;
        if (profile.Finalmask.IsNullOrEmpty()) profile.Finalmask = Fragment;
        if (profile.GetNetwork() is "ws" or "httpupgrade") profile.Alpn = "http/1.1";
    }
}
