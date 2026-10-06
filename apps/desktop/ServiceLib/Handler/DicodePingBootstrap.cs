namespace ServiceLib.Handler;

/// <summary>
/// Supplies the single first-run subscription and removes the old placeholder named
/// "Default". Network work is intentionally left to the UI startup task so launching
/// the client never blocks on an unreachable subscription endpoint.
/// </summary>
public static class DicodePingBootstrap
{
    public const string DefaultSubscriptionUrl =
        "https://raw.githubusercontent.com/mcodersir/DicodeConfigChecker/refs/heads/main/sub.txt";

    /// <summary>
    ///     Marker URL of the DicodeSpo "sources" subscription. It is never fetched:
    ///     SubscriptionHandler aggregates the enabled free-config sources instead.
    /// </summary>
    public const string SpoSourcesSubUrl = "https://dicodeping.local/dicode-spo/sources";

    public const string SpoSourcesRemarks = "DicodeSpo · Sources";

    public static async Task EnsureDefaultsAsync(Config config)
    {
        var subscriptions = await AppManager.Instance.SubItems() ?? [];

        foreach (var obsolete in subscriptions.Where(item =>
                     string.Equals(item.Remarks, "Default", StringComparison.OrdinalIgnoreCase)))
        {
            await ConfigHandler.DeleteSubItem(config, obsolete.Id);
        }

        subscriptions = await AppManager.Instance.SubItems() ?? [];

        // DicodeSpo is the first subscription of the app.
        if (!subscriptions.Any(item => string.Equals(item.Url, SpoSourcesSubUrl, StringComparison.OrdinalIgnoreCase)))
        {
            await ConfigHandler.AddSubItem(config, new SubItem
            {
                Id = string.Empty,
                Remarks = SpoSourcesRemarks,
                Url = SpoSourcesSubUrl,
                Enabled = true,
                Sort = 0,
                AutoUpdateInterval = 6,
            });
        }

        // Keep the Config Checker subscription right behind it.
        foreach (var checker in subscriptions.Where(item =>
                     string.Equals(item.Url, DefaultSubscriptionUrl, StringComparison.OrdinalIgnoreCase)))
        {
            if (checker.Sort != 1)
            {
                checker.Sort = 1;
                await ConfigHandler.AddSubItem(config, checker);
            }
        }

        subscriptions = await AppManager.Instance.SubItems() ?? [];
        if (subscriptions.Any(item => string.Equals(item.Url, DefaultSubscriptionUrl, StringComparison.OrdinalIgnoreCase)))
        {
            return;
        }

        await ConfigHandler.AddSubItem(config, new SubItem
        {
            Id = string.Empty,
            Remarks = "Dicode Config Checker",
            Url = DefaultSubscriptionUrl,
            Enabled = true,
            Sort = 1,
            AutoUpdateInterval = 1,
        });
    }
}
