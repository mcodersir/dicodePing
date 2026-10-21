namespace ServiceLib.Services;

public record SponsorAd(string Title, string Body, string Url);
public static class RemoteAds
{
    public const string ConfigUrl = "https://raw.githubusercontent.com/mcodersir/dicodePing/refs/heads/main/ads.txt";
    public static SponsorAd? Parse(string json, string placement, bool persian)
    {
        if (json.Length > 131072 || placement is not ("home" or "profiles" or "fox")) return null;
        try {
            var root = JsonNode.Parse(json);
            if (root?["version"]?.GetValue<int>() != 1 || root["enabled"]?.GetValue<bool>() != true
                || root["placements"]?[placement]?.GetValue<bool>() != true || root["ads"] is not JsonArray ads) return null;
            foreach (var ad in ads.Take(20)) {
                if (ad?["enabled"]?.GetValue<bool>() != true || ad["placements"] is not JsonArray positions || !positions.Any(x => x?.ToString() == placement)) continue;
                var url = ad["target_url"]?.ToString() ?? "";
                if (url.Length > 2048 || !Uri.TryCreate(url, UriKind.Absolute, out var uri) || uri.Scheme != "https" || uri.UserInfo.Length > 0 || uri.IsLoopback || !uri.Host.Contains('.')) continue;
                var title = ad[persian ? "title_fa" : "title_en"]?.ToString() ?? "";
                var body = ad[persian ? "body_fa" : "body_en"]?.ToString() ?? "";
                if (string.IsNullOrWhiteSpace(title) || title.Length > 120 || body.Length > 400) continue;
                return new SponsorAd(title, body, uri.AbsoluteUri);
            }
        } catch (Exception) { }
        return null;
    }
    public static async Task<SponsorAd?> LoadAsync(string placement, bool persian, CancellationToken token)
    {
        try {
            using var client = new HttpClient { Timeout = TimeSpan.FromSeconds(4), MaxResponseContentBufferSize = 131072 };
            return Parse(await client.GetStringAsync(ConfigUrl, token), placement, persian);
        } catch (Exception) { return null; }
    }
}
