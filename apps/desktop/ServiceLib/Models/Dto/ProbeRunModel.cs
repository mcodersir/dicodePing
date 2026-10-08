namespace ServiceLib.Models.Dto;

public partial class ProbeRunModel : ReactiveObject
{
    private readonly HashSet<string> _completedIds = new(StringComparer.Ordinal);
    public string Name { get; init; } = "";
    public int Total { get; init; }
    public bool StopRequested { get; set; }
    public bool IsRunning { get; set; } = true;
    [Reactive] public partial int Completed { get; set; }
    [Reactive] public partial double Percent { get; set; }
    [Reactive] public partial string Summary { get; set; }
    public void Complete(string id)
    {
        if (!_completedIds.Add(id)) return;
        Completed = Math.Min(Total, _completedIds.Count);
        Percent = Total == 0 ? 0 : 100d * Completed / Total;
        UpdateSummary(ResUI.DicodeProbeRunning);
    }
    public void UpdateSummary(string state) => Summary = $"{Name} · {Completed} / {Total} · {state}";
}
