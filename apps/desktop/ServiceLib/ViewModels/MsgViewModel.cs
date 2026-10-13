namespace ServiceLib.ViewModels;

/// <summary>One parsed log entry for the Reports page.</summary>
public class LogItemModel
{
    public string Time { get; set; } = string.Empty;
    public string Level { get; set; } = "MSG";
    public string Content { get; set; } = string.Empty;

    public bool IsError => Level == "ERROR" || Level == "FATAL";
    public bool IsWarning => Level == "WARN";
    public bool IsInfo => Level == "INFO";
    public bool IsDebug => Level == "DEBUG";
}

public partial class MsgViewModel : MyReactiveObject
{
    private readonly List<LogItemModel> _allEntries = [];
    private int _lastMsgFilterNotAvailable;
    public int NumMaxMsg { get; } = 500;

    [Reactive]
    public partial string MsgFilter { get; set; }

    [Reactive]
    public partial bool AutoRefresh { get; set; }

    public ObservableCollection<LogItemModel> LogItems { get; } = [];

    public MsgViewModel()
    {
        _config = AppManager.Instance.Config;
        MsgFilter = _config.MsgUIItem.MainMsgFilter ?? string.Empty;
        AutoRefresh = _config.MsgUIItem.AutoRefresh ?? true;

        this.WhenAnyValue(x => x.MsgFilter)
            .Subscribe(_ =>
            {
                _config.MsgUIItem.MainMsgFilter = MsgFilter;
                _lastMsgFilterNotAvailable = 0;
                RebuildFiltered();
            });

        this.WhenAnyValue(x => x.AutoRefresh, y => y == true)
            .Subscribe(c => _config.MsgUIItem.AutoRefresh = AutoRefresh);

        AppEvents.SendMsgViewRequested
         .AsObservable()
         .Subscribe(content => AppendContent(content));

        // The event stream only contains messages produced after this view model
        // is created. Seed it from today's persistent file so opening the page
        // always shows useful startup, core and crash diagnostics as well.
        try
        {
            var logFile = Utils.GetLogPath($"{DateTime.Now:yyyy-MM-dd}.txt");
            if (File.Exists(logFile))
            {
                using var stream = new FileStream(logFile, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete);
                using var reader = new StreamReader(stream, Encoding.UTF8, true);
                var tail = new Queue<string>(NumMaxMsg * 4);
                while (reader.ReadLine() is { } line)
                {
                    if (tail.Count >= NumMaxMsg * 4)
                    {
                        tail.Dequeue();
                    }
                    tail.Enqueue(line);
                }
                AppendContent(string.Join(Environment.NewLine, tail));
            }
        }
        catch (Exception ex)
        {
            Logging.SaveLog("LoadLogHistory", ex);
        }
    }

    private void AppendContent(string content)
    {
        if (content.IsNullOrEmpty() || AutoRefresh == false)
        {
            return;
        }

        var parsed = ParseEntries(content);
        if (parsed.Count == 0)
        {
            return;
        }

        lock (_allEntries)
        {
            _allEntries.AddRange(parsed);
            while (_allEntries.Count > NumMaxMsg)
            {
                _allEntries.RemoveAt(0);
            }
        }

        RxSchedulers.MainThreadScheduler.Schedule(() => InsertParsed(parsed));
    }

    private void InsertParsed(List<LogItemModel> parsed)
    {
        foreach (var item in parsed)
        {
            if (PassesFilter(item))
            {
                LogItems.Add(item);
            }
        }
        while (LogItems.Count > NumMaxMsg)
        {
            LogItems.RemoveAt(0);
        }
    }

    private void RebuildFiltered()
    {
        RxSchedulers.MainThreadScheduler.Schedule(() =>
        {
            LogItems.Clear();
            List<LogItemModel> snapshot;
            lock (_allEntries)
            {
                snapshot = [.. _allEntries];
            }
            foreach (var item in snapshot)
            {
                if (PassesFilter(item))
                {
                    LogItems.Add(item);
                }
            }
            while (LogItems.Count > NumMaxMsg)
            {
                LogItems.RemoveAt(0);
            }
        });
    }

    private bool PassesFilter(LogItemModel item)
    {
        if (MsgFilter.IsNullOrEmpty())
        {
            return true;
        }
        try
        {
            return Regex.IsMatch($"{item.Time} {item.Level} {item.Content}", MsgFilter);
        }
        catch
        {
            return true;
        }
    }

    private static List<LogItemModel> ParseEntries(string content)
    {
        var entries = new List<LogItemModel>();
        var headerRegex = new Regex(
            @"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d+)?)-(INFO|ERROR|WARN|DEBUG|FATAL)\s?(.*)$",
            RegexOptions.Compiled);

        LogItemModel? current = null;
        foreach (var line in content.Replace("\r\n", "\n").Split('\n'))
        {
            if (line.IsNullOrEmpty())
            {
                continue;
            }
            var match = headerRegex.Match(line);
            if (match.Success)
            {
                current = new LogItemModel
                {
                    Time = match.Groups[1].Value,
                    Level = match.Groups[2].Value == "FATAL" ? "ERROR" : match.Groups[2].Value,
                    Content = match.Groups[3].Value,
                };
                entries.Add(current);
            }
            else if (current != null)
            {
                current.Content += Environment.NewLine + line;
            }
            else
            {
                current = new LogItemModel { Time = string.Empty, Level = "MSG", Content = line };
                entries.Add(current);
            }
        }
        return entries;
    }
}
