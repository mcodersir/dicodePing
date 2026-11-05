using ServiceLib.Services;
using Xunit;

namespace ServiceLib.Tests;

public class Release4998Tests
{
    [Fact]
    public async Task DuplicateQueueEntriesAreFlushedAsOneDatabaseRow()
    {
        SQLiteHelper.Instance.CreateTable<ProfileExItem>();
        var id = "flush-4998-" + Guid.NewGuid().ToString("N");
        var manager = new ProfileExManager();
        try
        {
            manager.SetTestDelay(id, 42);
            var queue = (System.Collections.Concurrent.ConcurrentQueue<string>)typeof(ProfileExManager)
                .GetField("_queIndexIds", BindingFlags.Instance | BindingFlags.NonPublic)!.GetValue(manager)!;
            // Deterministically reproduce a producer re-enqueueing the same ID
            // during a drain; a single SQLite insert batch must deduplicate it.
            queue.Enqueue(id);
            var method = typeof(ProfileExManager).GetMethod("SaveQueueIndexIds", BindingFlags.Instance | BindingFlags.NonPublic)!;
            await (Task)method.Invoke(manager, null)!;
            Assert.Single(await SQLiteHelper.Instance.TableAsync<ProfileExItem>().Where(row => row.IndexId == id).ToListAsync());
        }
        finally { await SQLiteHelper.Instance.ExecuteAsync($"DELETE FROM ProfileExItem WHERE IndexId = '{id}'"); }
    }
    [Theory]
    [InlineData(50_000_000_000L, 30_000_000_000L, 20_000_000_000L, 0.4)]
    [InlineData(50L, 80L, 0L, 0)]
    [InlineData(long.MaxValue, 0L, long.MaxValue, 1)]
    public void QuotaUsesProviderTotalAndClampsRemaining(long maximum, long remaining, long used, double fraction)
    {
        var quota = FoxQuota.From(maximum, remaining)!.Value;
        Assert.Equal(used, quota.Used);
        Assert.Equal(fraction, quota.Fraction, 6);
    }

    [Theory]
    [InlineData(null, null)]
    [InlineData(0L, 0L)]
    [InlineData(-1L, 10L)]
    [InlineData(50L, -1L)]
    public void MissingAllowanceNeverFabricatesFiftyGigabytes(long? maximum, long? remaining) =>
        Assert.Null(FoxQuota.From(maximum, remaining));
}
