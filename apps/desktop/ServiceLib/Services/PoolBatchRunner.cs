namespace ServiceLib.Services;

/// <summary>Isolate malformed native configurations without discarding their healthy neighbours.</summary>
public static class PoolBatchRunner
{
    public static async Task RunAsync<T>(IReadOnlyList<T> items, int batchSize,
        Func<T[], Task<bool>> tryBatch, Action<T> rejected, CancellationToken token)
    {
        var pending = new Queue<T[]>(items.Chunk(batchSize));
        while (pending.TryDequeue(out var batch))
        {
            token.ThrowIfCancellationRequested();
            if (await tryBatch(batch)) continue;
            token.ThrowIfCancellationRequested();
            if (batch.Length == 1) { rejected(batch[0]); continue; }
            var midpoint = batch.Length / 2;
            pending.Enqueue(batch[..midpoint]);
            pending.Enqueue(batch[midpoint..]);
        }
    }
}
