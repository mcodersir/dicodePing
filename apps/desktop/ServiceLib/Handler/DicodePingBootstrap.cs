namespace ServiceLib.Handler;

/// <summary>Idempotent built-in subscription migration; user subscriptions keep their identity.</summary>
public static class DicodePingBootstrap
{
    public const string DefaultSubscriptionUrl = "https://raw.githubusercontent.com/mcodersir/DicodeConfigChecker/refs/heads/main/sub.txt";
    public const string SecondarySubscriptionUrl = "https://raw.githubusercontent.com/patterniha/Free-Configs/main/configs.txt";
    public const string LegacySourcesUrl = "https://dicodeping.local/dicode-spo/sources";

    public static async Task EnsureDefaultsAsync(Config config)
    {
        var subscriptions = await AppManager.Instance.SubItems() ?? [];
        foreach (var item in subscriptions.Where(item =>
                     string.Equals(item.Url, LegacySourcesUrl, StringComparison.OrdinalIgnoreCase)
                     || (item.Remarks?.StartsWith("DicodeSpo", StringComparison.OrdinalIgnoreCase) ?? false)))
            await ConfigHandler.DeleteSubItem(config, item.Id);

        subscriptions = await AppManager.Instance.SubItems() ?? [];
        var checker = subscriptions.FirstOrDefault(item => string.Equals(item.Url, DefaultSubscriptionUrl, StringComparison.OrdinalIgnoreCase))
            ?? new SubItem { Id = string.Empty, Enabled = true, AutoUpdateInterval = 1 };
        ConfigurePrimarySubscription(checker);
        await ConfigHandler.AddSubItem(config, checker);
    }

    public static void ConfigurePrimarySubscription(SubItem checker)
    {
        checker.Remarks = "Dicode Config Checker";
        checker.Url = DefaultSubscriptionUrl;
        checker.Sort = 0;
        checker.MoreUrl = string.Join(",", (checker.MoreUrl ?? string.Empty).Split(',', StringSplitOptions.TrimEntries | StringSplitOptions.RemoveEmptyEntries)
            .Append(SecondarySubscriptionUrl).Distinct(StringComparer.OrdinalIgnoreCase));
    }
}
