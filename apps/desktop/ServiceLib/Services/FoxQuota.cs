namespace ServiceLib.Services;

/// <summary>Provider allowance, never an estimate based on local traffic counters.</summary>
public readonly record struct FoxQuota(long Maximum, long Remaining)
{
    public long Used => Maximum - Remaining;
    public double Fraction => (double)Used / Maximum;
    public static FoxQuota? From(long? maximum, long? remaining) =>
        maximum is > 0 && remaining is >= 0
            ? new FoxQuota(maximum.Value, Math.Min(maximum.Value, remaining.Value)) : null;
}
