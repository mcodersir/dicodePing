namespace NativeWebView.Platform.Linux;

internal sealed class LinuxRuntimeNavigationLifecycle
{
    private ulong _currentNavigationId;
    private int _pendingFailedFinishes;

    public ulong CurrentNavigationId => _currentNavigationId;

    public ulong StartNavigation()
    {
        _currentNavigationId = unchecked(_currentNavigationId + 1);
        return _currentNavigationId;
    }

    public ulong FailNavigation()
    {
        if (_pendingFailedFinishes < int.MaxValue)
            _pendingFailedFinishes++;
        return _currentNavigationId;
    }

    public bool TryFinishNavigation(out ulong navigationId)
    {
        navigationId = _currentNavigationId;
        if (_pendingFailedFinishes == 0)
            return true;

        // WebKit emits Finished after load-failed. Consume that terminal signal without
        // applying it to a navigation that may have started reentrantly in the failure callback.
        _pendingFailedFinishes--;
        return false;
    }

    public void RuntimeDestroyed()
    {
        _pendingFailedFinishes = 0;
    }
}
