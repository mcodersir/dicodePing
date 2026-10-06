namespace ServiceLib.Handler;

/// <summary>
///     Aggregates the free-config sources behind the DicodeSpo subscription.
///     Sources are fetched in priority order; plain config links are taken as-is
///     and base64 bodies are decoded. Results are deduplicated and capped so the
///     resulting subscription stays light even with the heavy dump sources.
/// </summary>
public static class SpoSourcesService
{
    private const string _tag = "SpoSourcesService";
    private static readonly Regex ConfigLinkRegex =
        new(@"(?:vmess|vless|trojan|ss|ssr|hysteria2?|hy2|tuic)://[^\s""'<>\\]+", RegexOptions.Compiled);

    public static List<SpoSourceItem> GetSources()
    {
        var configured = AppManager.Instance.Config.SpoSourcesItem?.Sources;
        return configured is { Count: > 0 }
            ? configured.Where(s => s.Enabled && s.Name.IsNotEmpty() && s.Url.IsNotEmpty()).ToList()
            : SpoSourceDefaults.Sources;
    }

    public static async Task<string> BuildSubscriptionTextAsync(Config config)
    {
        var maxConfigs = config.SpoSourcesItem?.MaxConfigs is > 0 and <= 5000
            ? config.SpoSourcesItem.MaxConfigs
            : 500;

        var collected = new List<string>();
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var sourceReport = new List<string>();

        foreach (var source in GetSources())
        {
            if (collected.Count >= maxConfigs)
            {
                break;
            }

            try
            {
                var downloadHandle = new DownloadService();
                var body = await downloadHandle.TryDownloadString(source.Url, false, Global.AppName);
                var links = ExtractLinks(body ?? string.Empty);

                var added = 0;
                foreach (var link in links)
                {
                    if (collected.Count >= maxConfigs)
                    {
                        break;
                    }
                    if (seen.Add(link))
                    {
                        collected.Add(link);
                        added++;
                    }
                }
                sourceReport.Add($"{source.Name}: {added}");
            }
            catch (Exception ex)
            {
                Logging.SaveLog($"{_tag}: {source.Name}", ex);
                sourceReport.Add($"{source.Name}: failed");
            }
        }

        Logging.SaveLog($"{_tag} collected {collected.Count} configs ({string.Join(", ", sourceReport)})");
        return string.Join(Environment.NewLine, collected);
    }

    private static List<string> ExtractLinks(string body)
    {
        if (body.IsNullOrEmpty())
        {
            return [];
        }

        var links = ConfigLinkRegex.Matches(body)
            .Select(m => m.Value.Trim())
            .Where(l => l.Length > 8)
            .ToList();

        if (links.Count == 0)
        {
            // The whole body may be a base64 subscription; decode and re-scan.
            try
            {
                var decoded = Utils.Base64Decode(body.Trim());
                links = ConfigLinkRegex.Matches(decoded)
                    .Select(m => m.Value.Trim())
                    .Where(l => l.Length > 8)
                    .ToList();
            }
            catch
            {
                // Not base64 either — nothing usable in this source.
            }
        }

        return links;
    }
}
