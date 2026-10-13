namespace ServiceLib.Services;

public class ProcessService : IDisposable
{
    private readonly Process _process;
    private readonly bool _privateProtocol;
    private readonly Func<bool, string, Task>? _updateFunc;
    private bool _isDisposed;
    private readonly Queue<string> _recentOutput = new();
    private readonly object _outputLock = new();

    public int Id => _process.Id;
    public IntPtr Handle => _process.Handle;
    public bool HasExited => _process.HasExited;
    public string? TemporaryConfigPath { get; set; }
    public bool StopRequested { get; private set; }
    public event Action<int>? Exited;

    /// <summary>Last captured output lines (oldest first) for failure diagnostics.</summary>
    public string RecentOutput
    {
        get
        {
            lock (_outputLock)
            {
                return string.Join(Environment.NewLine, _recentOutput);
            }
        }
    }

    public ProcessService(
        string fileName,
        string arguments,
        string workingDirectory,
        bool displayLog,
        bool redirectInput,
        Dictionary<string, string>? environmentVars,
        Func<bool, string, Task>? updateFunc, bool privateProtocol = false)
    {
        _updateFunc = updateFunc;
        _privateProtocol = privateProtocol;

        _process = new Process
        {
            StartInfo = new ProcessStartInfo
            {
                FileName = fileName,
                Arguments = arguments,
                WorkingDirectory = workingDirectory,
                UseShellExecute = false,
                RedirectStandardInput = redirectInput,
                RedirectStandardOutput = displayLog || privateProtocol,
                RedirectStandardError = displayLog || privateProtocol,
                CreateNoWindow = true,
                StandardOutputEncoding = displayLog || privateProtocol ? Encoding.UTF8 : null,
                StandardErrorEncoding = displayLog || privateProtocol ? Encoding.UTF8 : null,
            },
            EnableRaisingEvents = true
        };

        if (environmentVars != null)
        {
            foreach (var kv in environmentVars)
            {
                _process.StartInfo.Environment[kv.Key] = kv.Value;
            }
        }

        _process.Exited += (_, _) =>
        {
            var exitCode = -1;
            try { exitCode = _process.ExitCode; } catch { }
            Exited?.Invoke(exitCode);
        };

        if (displayLog && !privateProtocol)
        {
            RegisterEventHandlers();
        }
    }

    public async Task StartAsync(string pwd = null)
    {
        _process.Start();

        if (_process.StartInfo.RedirectStandardOutput)
        {
            _process.BeginOutputReadLine();
            _process.BeginErrorReadLine();
        }

        if (_process.StartInfo.RedirectStandardInput)
        {
            await Task.Delay(10);
            await _process.StandardInput.WriteLineAsync(pwd);
        }
    }

    public async Task<JsonObject> StartPrivateProtocolAsync(JsonObject request, Func<JsonObject, Task>? onEvent, CancellationToken token)
    {
        if (!_privateProtocol) throw new InvalidOperationException("Not a private helper process");
        _process.Start();
        await _process.StandardInput.WriteLineAsync(request.ToJsonString().AsMemory(), token);
        await _process.StandardInput.FlushAsync(token);
        // Never forward protocol output to UI logs: it carries account tokens.
        _ = Task.Run(async () => { try { while (await _process.StandardError.ReadLineAsync() is { }) { } } catch (Exception) { /* Owned private pipe closed. */ } });
        var line = await _process.StandardOutput.ReadLineAsync(token);
        var result = JsonNode.Parse(line ?? "{}") as JsonObject ?? new JsonObject();
        if (result["ok"]?.GetValue<bool>() != true)
            throw new FoxException(result["error"]?.ToString() ?? "helper", result["message"]?.ToString() ?? "Fox helper did not start");
        if (onEvent is not null) _ = Task.Run(async () => {
            try {
                while (await _process.StandardOutput.ReadLineAsync() is { } next)
                    if (JsonNode.Parse(next) is JsonObject message) await onEvent(message);
            } catch (Exception) { /* Stopping an owned helper closes the private pipe. */ }
        });
        return result;
    }

    public async Task StopAsync()
    {
        StopRequested = true;
        if (_privateProtocol) { try { _process.StandardInput.Close(); } catch { } }
        try { if (_process.HasExited) return; }
        catch (InvalidOperationException) { return; }

        try
        {
            if (_process.StartInfo.RedirectStandardOutput)
            {
                try
                {
                    _process.CancelOutputRead();
                }
                catch { }
                try
                {
                    _process.CancelErrorRead();
                }
                catch { }
            }

            try
            {
                if (Utils.IsNonWindows())
                {
                    _process.Kill(true);
                }
            }
            catch { }

            try
            {
                _process.Kill();
            }
            catch { }
            try
            {
                using var exitTimeout = new CancellationTokenSource(TimeSpan.FromSeconds(3));
                await _process.WaitForExitAsync(exitTimeout.Token);
            }
            catch (OperationCanceledException)
            {
                await (_updateFunc?.Invoke(false, "Core shutdown timed out; cleaning stale resources before restart.") ?? Task.CompletedTask);
            }
        }
        catch (Exception ex)
        {
            await (_updateFunc?.Invoke(true, ex.Message) ?? Task.CompletedTask);
        }
    }

    private void RegisterEventHandlers()
    {
        void dataHandler(object sender, DataReceivedEventArgs e)
        {
            if (e.Data.IsNotEmpty())
            {
                lock (_outputLock)
                {
                    _recentOutput.Enqueue(e.Data);
                    while (_recentOutput.Count > 20)
                    {
                        _recentOutput.Dequeue();
                    }
                }
                // Persist every core line: the gui log is what "لطفاً گزارش را ببینید"
                // points at, so it must contain the core's own diagnostics too.
                Logging.SaveLog("Core: " + e.Data);
                _ = _updateFunc?.Invoke(false, e.Data + Environment.NewLine);
            }
        }

        _process.OutputDataReceived += dataHandler;
        _process.ErrorDataReceived += dataHandler;

        _process.Exited += (s, e) =>
        {
            try
            {
                _process.OutputDataReceived -= dataHandler;
                _process.ErrorDataReceived -= dataHandler;
            }
            catch
            {
            }
        };
    }

    public void Dispose()
    {
        if (_isDisposed)
        {
            return;
        }

        try
        {
            if (!_process.HasExited)
            {
                try
                {
                    _process.CancelOutputRead();
                }
                catch { }
                try
                {
                    _process.CancelErrorRead();
                }
                catch { }

                _process.Kill();
            }

            _process.Dispose();
        }
        catch (Exception ex)
        {
            _updateFunc?.Invoke(true, ex.Message);
        }

        if (TemporaryConfigPath is not null)
        {
            try { File.Delete(TemporaryConfigPath); } catch (Exception ex) { Logging.SaveLog("Temporary probe cleanup", ex); }
        }
        _isDisposed = true;
        GC.SuppressFinalize(this);
    }
}
