using System.Collections;

namespace ServiceLib.Helper;

public sealed class SQLiteHelper
{
    public Task ReplaceServerPoolAsync(string poolId, List<ProfileItem> profiles, string? selectedId) =>
        _dbAsync.RunInTransactionAsync(db =>
        {
            // Preserve an actively selected profile until the user switches away.
            db.Execute("DELETE FROM ProfileItem WHERE Subid = ? AND IndexId != ?", poolId, selectedId ?? "");
            db.InsertAll(profiles);
        });

    private static readonly Lazy<SQLiteHelper> _instance = new(() => new());
    public static SQLiteHelper Instance => _instance.Value;
    private readonly string _connstr;
    private SQLiteConnection _db;
    private SQLiteAsyncConnection _dbAsync;
    private readonly string _configDB = "guiNDB.db";

    public SQLiteHelper()
    {
        _connstr = Utils.GetConfigPath(_configDB);
        _db = new SQLiteConnection(_connstr, false);
        // Native FullMutex serializes statements, not an entire managed transaction.
        // Keep sqlite-net's connection lock so concurrent pool/import/metrics
        // writes cannot invalidate one another's transaction savepoints.
        _dbAsync = new SQLiteAsyncConnection(_connstr,
            SQLiteOpenFlags.ReadWrite | SQLiteOpenFlags.Create, false);
    }

    public CreateTableResult CreateTable<T>()
    {
        return _db.CreateTable<T>();
    }

    public async Task<int> InsertAllAsync(IEnumerable models)
    {
        return await _dbAsync.InsertAllAsync(models, runInTransaction: true).ConfigureAwait(false);
    }

    public async Task<int> InsertAsync(object model)
    {
        return await _dbAsync.InsertAsync(model);
    }

    public async Task<int> ReplaceAsync(object model)
    {
        return await _dbAsync.InsertOrReplaceAsync(model);
    }

    public async Task<int> UpdateAsync(object model)
    {
        return await _dbAsync.UpdateAsync(model);
    }

    public async Task<int> UpdateAllAsync(IEnumerable models)
    {
        return await _dbAsync.UpdateAllAsync(models, runInTransaction: true).ConfigureAwait(false);
    }

    public async Task<int> DeleteAsync(object model)
    {
        return await _dbAsync.DeleteAsync(model);
    }

    public async Task<int> DeleteAllAsync<T>()
    {
        return await _dbAsync.DeleteAllAsync<T>();
    }

    public async Task<int> ExecuteAsync(string sql)
    {
        return await _dbAsync.ExecuteAsync(sql);
    }

    public async Task<List<T>> QueryAsync<T>(string sql) where T : new()
    {
        return await _dbAsync.QueryAsync<T>(sql);
    }

    public AsyncTableQuery<T> TableAsync<T>() where T : new()
    {
        return _dbAsync.Table<T>();
    }

    public async Task DisposeDbConnectionAsync()
    {
        // Close through the same pooled connection lock used by outstanding operations.
        await _dbAsync.CloseAsync();
        _db.Close();
        _db.Dispose();
    }
}
