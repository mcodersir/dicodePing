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
    public static (string Email, string Session)? Parse(string? currentUrl, string? payload, string nonce) => ParseSession(currentUrl, payload, nonce, "session");
    public static (string Email, string Session)? ParsePending(string? currentUrl, string? payload, string nonce) => ParseSession(currentUrl, payload, nonce, "pending_session");
    public static bool IsReady(string? currentUrl, string? payload, string nonce)
    {
        if (!IsTrusted(currentUrl) || string.IsNullOrEmpty(payload) || payload.Length > 8192) return false;
        try { var data=JsonNode.Parse(payload); return data?["nonce"]?.ToString()==nonce && data["kind"]?.ToString()=="bridge_ready"; }
        catch (Exception error) when (error is JsonException or InvalidOperationException) { return false; }
    }
    static (string Email, string Session)? ParseSession(string? currentUrl, string? payload, string nonce, string kind)
    {
        if (!IsTrusted(currentUrl) || string.IsNullOrEmpty(payload) || payload.Length > 8192) return null;
        try {
            var data = JsonNode.Parse(payload) as JsonObject;
            if (data?["nonce"]?.ToString() != nonce || data["kind"]?.ToString() != kind) return null;
            var session = data["session_token"]?.ToString() ?? ""; var email = data["email"]?.ToString() ?? "";
            return Regex.IsMatch(session, "\\A[a-fA-F0-9]{64}\\z") && email.Length <= 254 && email.Contains('@') ? (email, session) : null;
        } catch (JsonException) { return null; }
    }
    public static JsonObject? ParseGrant(string? currentUrl, string? payload, string nonce)
    {
        if (!IsTrusted(currentUrl) || string.IsNullOrEmpty(payload) || payload.Length > 8192) return null;
        try
        {
            var data = JsonNode.Parse(payload) as JsonObject;
            if (data?["nonce"]?.ToString() != nonce || data["kind"]?.ToString() != "grant") return null;
            var email = data["email"]?.GetValue<string>() ?? "";
            var access = data["access_token"]?.GetValue<string>() ?? "";
            var refresh = data["refresh_token"]?.GetValue<string>();
            var seconds = data["expires_in"]?.GetValue<long>() ?? 0;
            static bool Valid(string value) => Regex.IsMatch(value, "\\A[A-Za-z0-9._~+/\\-]{16,2048}\\z");
            if (email.Length > 254 || !email.Contains('@') || email.Any(char.IsControl) || !Valid(access)
                || refresh is not null && !Valid(refresh) || seconds <= 0 || seconds > 31536000) return null;
            return new JsonObject { ["email"] = email, ["access_token"] = access, ["refresh_token"] = refresh,
                ["expires_at"] = DateTimeOffset.UtcNow.ToUnixTimeSeconds() + seconds };
        }
        catch (Exception error) when (error is JsonException or InvalidOperationException or FormatException) { return null; }
    }
}
