namespace ServiceLib.Manager;

/// <summary>
/// Serializes operations that replace profile ids or own temporary core ports.
/// Subscription replacement, latency/location tests and TUN startup must never
/// mutate the same profile set concurrently.
/// </summary>
public static class ProfileOperationCoordinator
{
    public static SemaphoreSlim Gate { get; } = new(1, 1);
}
