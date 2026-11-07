using NLog;
using NLog.Config;
using NLog.Targets;

namespace ServiceLib.Common;

public class Logging
{
    private static readonly Logger _logger1 = LogManager.GetLogger("Log1");
    private static readonly Logger _logger2 = LogManager.GetLogger("Log2");

    public static void Setup()
    {
        LoggingConfiguration config = new();
        FileTarget fileTarget = new();
        config.AddTarget("file", fileTarget);
        fileTarget.Layout = "${longdate}-${level:uppercase=true} ${message}";
        fileTarget.FileName = Utils.GetLogPath("${shortdate}.txt");
        fileTarget.ArchiveAboveSize = 5 * 1024 * 1024;
        fileTarget.MaxArchiveFiles = 6;
        var asyncTarget = new NLog.Targets.Wrappers.AsyncTargetWrapper(fileTarget, 2048, NLog.Targets.Wrappers.AsyncTargetWrapperOverflowAction.Discard);
        config.LoggingRules.Add(new LoggingRule("*", LogLevel.Debug, LogLevel.Info, asyncTarget));
        config.LoggingRules.Add(new LoggingRule("*", LogLevel.Warn, LogLevel.Fatal, fileTarget));
        LogManager.Configuration = config;
    }

    public static void LoggingEnabled(bool enable)
    {
        if (!enable) LogManager.SuspendLogging();
        else LogManager.ResumeLogging();
    }

    public static void SaveLog(string strContent)
    {
        if (!LogManager.IsLoggingEnabled())
        {
            return;
        }

        strContent = ServiceLib.Services.DiagnosticArchive.Redact(strContent);
        _logger1.Info(strContent);
        AppEvents.SendMsgViewRequested.Publish($"{DateTime.Now:yyyy-MM-dd HH:mm:ss}-INFO {strContent}");
    }

    public static void SaveLog(string strTitle, Exception ex)
    {
        if (!LogManager.IsLoggingEnabled())
        {
            return;
        }

        strTitle = ServiceLib.Services.DiagnosticArchive.Redact(strTitle);
        var safeError = ServiceLib.Services.DiagnosticArchive.Redact(ex.ToString());
        _logger2.Error($"{strTitle}: {safeError}");
        AppEvents.SendMsgViewRequested.Publish($"{DateTime.Now:yyyy-MM-dd HH:mm:ss}-ERROR {strTitle}: {ServiceLib.Services.DiagnosticArchive.Redact(ex.Message)}");

        if (ex?.InnerException != null)
        {
            _logger2.Error(ServiceLib.Services.DiagnosticArchive.Redact(ex.InnerException.ToString()));
        }
    }
}
