namespace ServiceLib.Models.Dto;

[Serializable]
public partial class ProfileItemModel : ReactiveObject
{
    public bool IsActive { get; set; }
    public string IndexId { get; set; }
    public EConfigType ConfigType { get; set; }
    public string Remarks { get; set; }
    public string Address { get; set; }
    public int Port { get; set; }
    public string Network { get; set; }
    public string StreamSecurity { get; set; }
    public string Subid { get; set; }
    public string SubRemarks { get; set; }
    public string SubscriptionUsage { get; set; }
    public bool HasSubscriptionUsage => SubscriptionUsage.IsNotEmpty();
    public int Sort { get; set; }

    [Reactive]
    public partial int Delay { get; set; }

    public decimal Speed { get; set; }

    [Reactive]
    public partial string DelayVal { get; set; }

    [Reactive]
    public partial string SpeedVal { get; set; }

    [Reactive]
    public partial string IpInfo { get; set; }

    [Reactive]
    public partial string SecurityInfo { get; set; }

    [Reactive]
    public partial string SanctionsInfo { get; set; }

    [Reactive]
    public partial string TodayUp { get; set; }

    [Reactive]
    public partial string TodayDown { get; set; }

    [Reactive]
    public partial string TotalUp { get; set; }

    [Reactive]
    public partial string TotalDown { get; set; }

    /// <summary>
    /// True while a latency/location test for this row is in flight; drives
    /// the shimmer placeholder in the results grid.
    /// </summary>
    [Reactive]
    public partial bool IsTesting { get; set; }

    [Reactive]
    public partial bool IsLatencyTesting { get; set; }

    [Reactive]
    public partial bool IsSpeedTesting { get; set; }

    [Reactive]
    public partial bool IsLocationTesting { get; set; }

    [Reactive]
    public partial bool IsSecurityTesting { get; set; }

    [Reactive]
    public partial bool IsSanctionsTesting { get; set; }

    public string GetSummary()
    {
        var summary = $"[{ConfigType}] {Remarks}";
        if (!ConfigType.IsComplexType())
        {
            summary += $"({Address}:{Port})";
        }

        return summary;
    }
}
