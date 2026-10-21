using AwesomeAssertions;
using ServiceLib.Manager;
using Xunit;
namespace ServiceLib.Tests.Manager;

public class ProfileExManagerConcurrencyTests
{
    [Fact]
    public async Task SetTestDelay_FromManyThreads_ShouldNotThrow()
    {
        var manager = CreateManager();
        var exceptions = new List<Exception>();
        var threads = Math.Clamp(Environment.ProcessorCount * 2, 4, 8);

        //Hammer the same manager from several streams at once: the queue is mutated while
        //other threads keep pushing into it
        var barrier = new Barrier(threads);
        Parallel.For(0, threads, new ParallelOptions { MaxDegreeOfParallelism = threads }, t =>
        {
            barrier.SignalAndWait();
            for (var i = 0; i < 5000; i++)
            {
                try
                {
                    manager.SetTestDelay($"index{i % 500}", i);
                }
                catch (Exception ex)
                {
                    lock (exceptions)
                    {
                        exceptions.Add(ex);
                    }
                }
            }
        });

        exceptions.Count.Should().Be(0);
    }

    [Fact]
    public async Task SetTestDelay_FromManyThreads_ShouldNotLoseQueuedIds()
    {
        var manager = CreateManager();
        var ids = 500;

        Parallel.For(0, Math.Clamp(Environment.ProcessorCount * 2, 4, 8), t =>
        {
            for (var i = 0; i < 5000; i++)
            {
                manager.SetTestDelay($"id{i % ids}", i);
            }
        });

        var drained = Drain(manager);
        drained.Count.Should().BeGreaterThanOrEqualTo(ids);
        drained.Distinct().Count().Should().Be(ids);
    }

    [Fact]
    public async Task SetTestDelay_ShouldCreateOneEntryPerIndex()
    {
        var manager = CreateManager();

        await Parallel.ForEachAsync(Enumerable.Range(0, 500), new ParallelOptions { MaxDegreeOfParallelism = 32 },
            async (i, ct) =>
            {
                manager.SetTestDelay($"same{i % 10}", i);
                await Task.CompletedTask;
            });

        var items = await manager.GetProfileExs();
        items.Count.Should().Be(10);
        items.Select(t => t.IndexId).Distinct().Count().Should().Be(10);
    }

    private static ProfileExManager CreateManager()
    {
        return (ProfileExManager)Activator.CreateInstance(typeof(ProfileExManager), nonPublic: true)!;
    }

    private static List<string> Drain(ProfileExManager manager)
    {
        var queue = (System.Collections.Concurrent.ConcurrentQueue<string>)typeof(ProfileExManager)
            .GetField("_queIndexIds", BindingFlags.Instance | BindingFlags.NonPublic)!
            .GetValue(manager)!;

        var result = new List<string>();
        while (queue.TryDequeue(out var id))
        {
            result.Add(id);
        }
        return result;
    }
}