namespace ServiceLib.Handler;

/// <summary>Idempotent built-in subscription migration; user subscriptions keep their identity.</summary>
public static class DicodePingBootstrap
{
    public const string DefaultSubscriptionUrl = "https://raw.githubusercontent.com/mcodersir/DicodeConfigChecker/refs/heads/main/sub.txt";
    public const string SecondarySubscriptionUrl = "https://raw.githubusercontent.com/patterniha/Free-Configs/main/configs.txt";
    public const string LegacySourcesUrl = "https://dicodeping.local/dicode-spo/sources";
    public const string ServerlessSubscriptionUrl = "https://raw.githubusercontent.com/patterniha/Serverless-for-Iran/refs/heads/main/Subscription/Serverless-for-Iran.json#Patterniha-S";

    public static async Task EnsureDefaultsAsync(Config config, bool freshInstall = false)
    {
        var subscriptions = await AppManager.Instance.SubItems() ?? [];
        if (!config.GuiItem.ServerlessProvisioned4998)
        {
            if (!subscriptions.Any(item => string.Equals(item.Url?.Split('#')[0], ServerlessSubscriptionUrl.Split('#')[0], StringComparison.OrdinalIgnoreCase)))
                await ConfigHandler.AddSubItem(config, new SubItem { Id = string.Empty, Remarks = "DicodeNV", Url = ServerlessSubscriptionUrl, Enabled = true, AutoUpdateInterval = 1 });
            config.GuiItem.ServerlessProvisioned4998 = true;
            await ConfigHandler.SaveConfig(config);
        }
        foreach (var feed in (await AppManager.Instance.SubItems() ?? []).Where(item =>
                     string.Equals(item.Url?.Split('#')[0], ServerlessSubscriptionUrl.Split('#')[0], StringComparison.OrdinalIgnoreCase)))
        {
            feed.Remarks = "DicodeNV";
            feed.Sort = 1;
            await ConfigHandler.AddSubItem(config, feed);
        }
        var nextSort = 2;
        foreach (var other in (await AppManager.Instance.SubItems() ?? []).Where(item =>
                     !string.Equals(item.Url, DefaultSubscriptionUrl, StringComparison.OrdinalIgnoreCase) &&
                     !string.Equals(item.Url?.Split('#')[0], ServerlessSubscriptionUrl.Split('#')[0], StringComparison.OrdinalIgnoreCase)))
        {
            if (other.Sort > 1) continue;
            other.Sort = nextSort++;
            await ConfigHandler.AddSubItem(config, other);
        }
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
