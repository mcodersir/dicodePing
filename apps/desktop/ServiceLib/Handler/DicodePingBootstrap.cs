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

    public static async Task EnsureDefaultsAsync(Config config)
    {
        var subscriptions = await AppManager.Instance.SubItems() ?? [];

        foreach (var obsolete in subscriptions.Where(item =>
                     string.Equals(item.Remarks, "Default", StringComparison.OrdinalIgnoreCase)))
        {
            await ConfigHandler.DeleteSubItem(config, obsolete.Id);
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
            AutoUpdateInterval = 1,
        });
    }
}
