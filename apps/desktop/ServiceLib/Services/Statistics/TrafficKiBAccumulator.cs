namespace ServiceLib.Services.Statistics;
// Existing persisted counters use KiB. Carry partial bytes across samples instead of discarding them each second.
public sealed class TrafficKiBAccumulator
{
    private ulong _up, _down;
    public (long Up, long Down) Add(ulong up, ulong down)
    {
        var upload = up / 1024; var download = down / 1024;
        _up += up % 1024; _down += down % 1024;
        upload += _up / 1024; download += _down / 1024; _up %= 1024; _down %= 1024;
        return ((long)upload, (long)download);
    }
    public void Reset() { _up = _down = 0; }
}
