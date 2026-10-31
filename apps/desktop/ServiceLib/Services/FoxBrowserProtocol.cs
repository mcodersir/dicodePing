using System.Text.RegularExpressions;

namespace ServiceLib.Services;

public static class FoxBrowserProtocol
{
    public const string LoginUrl = "https://accounts.firefox.com/?context=fx_desktop_v3&service=sync&action=email";
    public static bool IsTrusted(string? address) => Uri.TryCreate(address, UriKind.Absolute, out var uri)
        && uri.Scheme == Uri.UriSchemeHttps && uri.IdnHost == "accounts.firefox.com" && uri.Port == 443 && string.IsNullOrEmpty(uri.UserInfo);
    public static string Script(string nonce)
    {
        using var stream = typeof(FoxBrowserProtocol).Assembly.GetManifestResourceStream("DicodePing.FoxBrowser.js")!;
        return new StreamReader(stream).ReadToEnd().Replace("__DICODE_NONCE__", JsonSerializer.Serialize(nonce));
    }
    public static (string Email, string Session)? Parse(string? currentUrl, string? payload, string nonce)
    {
        if (!IsTrusted(currentUrl) || string.IsNullOrEmpty(payload) || payload.Length > 8192) return null;
        try {
            var data = JsonNode.Parse(payload) as JsonObject;
            if (data?["nonce"]?.ToString() != nonce || data["kind"]?.ToString() != "session") return null;
            var session = data["session_token"]?.ToString() ?? ""; var email = data["email"]?.ToString() ?? "";
            return Regex.IsMatch(session, "\\A[a-fA-F0-9]{64}\\z") && email.Length <= 254 && email.Contains('@') ? (email, session) : null;
        } catch (JsonException) { return null; }
    }
}
