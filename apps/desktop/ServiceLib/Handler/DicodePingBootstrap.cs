namespace ServiceLib.Handler;

/// <summary>Idempotent built-in subscription migration; user subscriptions keep their identity.</summary>
public static class DicodePingBootstrap
{
    public const string DefaultSubscriptionUrl = "https://raw.githubusercontent.com/mcodersir/DicodeConfigChecker/refs/heads/main/sub.txt";
    public const string SecondarySubscriptionUrl = "https://raw.githubusercontent.com/patterniha/Free-Configs/main/configs.txt";
    public const string LegacySourcesUrl = "https://dicodeping.local/dicode-spo/sources";

    public static async Task EnsureDefaultsAsync(Config config, bool freshInstall = false)
    {
        var subscriptions = await AppManager.Instance.SubItems() ?? [];
        foreach (var item in subscriptions.Where(item =>
                     string.Equals(item.Url, LegacySourcesUrl, StringComparison.OrdinalIgnoreCase)
                     || (item.Remarks?.StartsWith("DicodeSpo", StringComparison.OrdinalIgnoreCase) ?? false)))
            await ConfigHandler.DeleteSubItem(config, item.Id);

        subscriptions = await AppManager.Instance.SubItems() ?? [];
        var checker = subscriptions.FirstOrDefault(item => string.Equals(item.Url, DefaultSubscriptionUrl, StringComparison.OrdinalIgnoreCase));
        if (checker is null && !freshInstall) return;
        checker ??= new SubItem { Id = string.Empty, Enabled = true, AutoUpdateInterval = 1 };
        if (!config.GuiItem.SubscriptionsSplit497)
        {
            var secondary = subscriptions.FirstOrDefault(item => string.Equals(item.Url, SecondarySubscriptionUrl, StringComparison.OrdinalIgnoreCase));
            secondary ??= new SubItem { Id = string.Empty, Remarks = "Community configs", Url = SecondarySubscriptionUrl, Enabled = true, AutoUpdateInterval = 1 };
            await ConfigHandler.AddSubItem(config, secondary);
            if (!freshInstall && checker.Id.IsNotEmpty())
            {
                var legacy = await AppManager.Instance.ProfileItems(checker.Id) ?? [];
                foreach (var profile in legacy) profile.Subid = secondary.Id;
                if (legacy.Count > 0) await SQLiteHelper.Instance.UpdateAllAsync(legacy);
            }
            config.GuiItem.SubscriptionsSplit497 = true;
            await ConfigHandler.SaveConfig(config);
        }
        ConfigurePrimarySubscription(checker);
        await ConfigHandler.AddSubItem(config, checker);
    }

    public static bool ShouldPrepare(Config config, SubItem? primary) =>
        config.GuiItem.AutoTestDefaultSubscription && primary?.Enabled == true;

    public static void ConfigurePrimarySubscription(SubItem checker)
    {
        checker.Remarks = "Dicode Config Checker";
        checker.Url = DefaultSubscriptionUrl;
        checker.Sort = 0;
        checker.MoreUrl = string.Empty;
    }
}
