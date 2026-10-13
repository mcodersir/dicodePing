using Xunit;

namespace ServiceLib.Tests;

public class PoolBatchRunnerTests
{
    [Fact]
    public async Task OneMalformedConfigDoesNotRejectTheHealthyBatch()
    {
        var tested = new List<int>();
        var rejected = new List<int>();
        await PoolBatchRunner.RunAsync<int>([1, 2, -1, 3, 4, 5], 12, batch => {
            if (batch.Contains(-1)) return Task.FromResult(false);
            tested.AddRange(batch);
            return Task.FromResult(true);
        }, rejected.Add, CancellationToken.None);
        Assert.Equal([1, 2, 3, 4, 5], tested.Order().ToArray());
        Assert.Equal([-1], rejected);
    }

    [Fact]
    public async Task CancellationStopsBatchSubdivision()
    {
        using var cts = new CancellationTokenSource();
        var calls = 0;
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => PoolBatchRunner.RunAsync<int>([1, 2, 3], 12, _ => {
            calls++; cts.Cancel(); return Task.FromResult(false);
        }, _ => Assert.Fail("Cancellation must not reject configs"), cts.Token));
        Assert.Equal(1, calls);
    }
}
