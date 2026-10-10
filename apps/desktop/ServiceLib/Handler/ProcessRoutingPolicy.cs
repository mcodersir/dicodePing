namespace ServiceLib.Handler;

public static class ProcessRoutingPolicy
{
    public static List<string> Normalize(IEnumerable<string> values) => values.Select(x => x.Trim().Trim('"').Replace('\\', '/'))
        .Where(x => x.IsNotEmpty() && !x.StartsWith('#')).Distinct(StringComparer.OrdinalIgnoreCase).ToList();
}
