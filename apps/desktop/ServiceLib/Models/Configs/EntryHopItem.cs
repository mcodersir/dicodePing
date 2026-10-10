namespace ServiceLib.Models.Configs;

public class EntryHopItem
{
    public bool Enabled { get; set; }
    public string Kind { get; set; } = "aether";
    public string ProfileId { get; set; } = "";
    public string SubscriptionId { get; set; } = "";
    public string Policy { get; set; } = "first";
    public int Port { get; set; } = 61080;
    public string LastTransport { get; set; } = "";
    public string NetworkKey { get; set; } = "";
    public int ConsecutiveFailures { get; set; }
    public int RescanAfterFailures { get; set; } = 3;
    public bool Applies(ProfileItem node) => Enabled && (ProfileId.IsNotEmpty() ? node.IndexId == ProfileId
        : SubscriptionId.IsNotEmpty() ? node.Subid == SubscriptionId : true);
}
