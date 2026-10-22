namespace ServiceLib.Services;

/// <summary>Only successful samples received by the current HTTP probe can become a candidate.</summary>
public sealed class SmartConnectCandidates(int limit)
{
    private readonly Dictionary<string, int> _samples = new(StringComparer.Ordinal);
    public string? BestId => _samples.OrderBy(x => x.Value).Select(x => x.Key).FirstOrDefault();
    public bool Add(string id, int delay)
    {
        if (_samples.Count >= limit) return true;
        if (!string.IsNullOrEmpty(id) && delay > 0) _samples[id] = delay;
        return _samples.Count >= limit;
    }
}
