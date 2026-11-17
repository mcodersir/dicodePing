using System.Runtime.Versioning;
using NativeWebView.Core;
using NativeWebView.Interop;

namespace NativeWebView.Platform.Linux;

public sealed class LinuxNativeWebDialogBackend : INativeWebDialogBackend, INativeWebDialogPlatformHandleProvider, INativeWebViewInstanceConfigurationTarget, INativeWebViewZoomFactorProvider
{
    private static readonly NativePlatformHandle PlaceholderPlatformHandle = new((nint)0x3101, "GtkWindow");
    private static readonly NativePlatformHandle PlaceholderDialogHandle = new((nint)0x3102, "WebKitWebView");
    private static readonly NativePlatformHandle PlaceholderHostWindowHandle = new((nint)0x3103, "XID");

    private readonly LinuxNativeWebViewBackend _backend = new();
    private readonly List<IDisposable> _windowSignalSubscriptions = [];

    private nint _gtkWindow;
    private nint _windowXid;

    private bool _isVisible;
    private bool _disposed;
    private bool _suppressDestroyNotification;

    public LinuxNativeWebDialogBackend()
    {
        Platform = NativeWebViewPlatform.Linux;
        Features = LinuxPlatformFeatures.Instance;

        _backend.NavigationStarted += OnNavigationStarted;
        _backend.NavigationCompleted += OnNavigationCompleted;
        _backend.WebMessageReceived += OnWebMessageReceived;
        _backend.NewWindowRequested += OnNewWindowRequested;
        _backend.WebResourceRequested += OnWebResourceRequested;
        _backend.ContextMenuRequested += OnContextMenuRequested;
        _backend.DestroyRequested += OnDestroyRequested;
        _backend.ZoomFactorChanged += OnZoomFactorChanged;
    }

    public NativeWebViewPlatform Platform { get; }

    public IWebViewPlatformFeatures Features { get; }

    public bool IsVisible => _isVisible;

    public Uri? CurrentUrl => _backend.CurrentUrl;

    public bool CanGoBack => _backend.CanGoBack;

    public bool CanGoForward => _backend.CanGoForward;

    public bool IsDevToolsEnabled
    {
        get => _backend.IsDevToolsEnabled;
        set
        {
            EnsureNotDisposed();
            _backend.IsDevToolsEnabled = value;
        }
    }

    public bool IsContextMenuEnabled
    {
        get => _backend.IsContextMenuEnabled;
        set
        {
            EnsureNotDisposed();
            _backend.IsContextMenuEnabled = value;
        }
    }

    public bool IsStatusBarEnabled
    {
        get => _backend.IsStatusBarEnabled;
        set
        {
            EnsureNotDisposed();
            _backend.IsStatusBarEnabled = value;
        }
    }

    public bool IsZoomControlEnabled
    {
        get => _backend.IsZoomControlEnabled;
        set
        {
            EnsureNotDisposed();
            _backend.IsZoomControlEnabled = value;
        }
    }

    public double ZoomFactor => _backend.ZoomFactor;

    public string? HeaderString => _backend.HeaderString;

    public string? UserAgentString => _backend.UserAgentString;

    public event EventHandler<EventArgs>? Shown;

    public event EventHandler<EventArgs>? Closed;

    public event EventHandler<NativeWebViewNavigationStartedEventArgs>? NavigationStarted;

    public event EventHandler<NativeWebViewNavigationCompletedEventArgs>? NavigationCompleted;

    public event EventHandler<NativeWebViewMessageReceivedEventArgs>? WebMessageReceived;

    public event EventHandler<NativeWebViewNewWindowRequestedEventArgs>? NewWindowRequested;

    public event EventHandler<NativeWebViewResourceRequestedEventArgs>? WebResourceRequested;

    public event EventHandler<NativeWebViewContextMenuRequestedEventArgs>? ContextMenuRequested;

    public event EventHandler<NativeWebViewZoomFactorChangedEventArgs>? ZoomFactorChanged;

    public void ApplyInstanceConfiguration(NativeWebViewInstanceConfiguration configuration)
    {
        ArgumentNullException.ThrowIfNull(configuration);
        EnsureNotDisposed();

        if (_backend is INativeWebViewInstanceConfigurationTarget configurationTarget)
        {
            configurationTarget.ApplyInstanceConfiguration(configuration);
        }
    }

    public void Show(NativeWebDialogShowOptions? options = null)
    {
        EnsureNotDisposed();
        EnsureFeature(NativeWebViewFeature.Dialog, nameof(Show));

        if (OperatingSystem.IsLinux())
        {
            EnsureWindowCreated();
            LinuxGtkDispatcher.InvokeAsync(
                () => ApplyWindowOptionsOnGtkThread(options),
                CancellationToken.None).GetAwaiter().GetResult();
        }

        _isVisible = true;
        Shown?.Invoke(this, EventArgs.Empty);
    }

    public void Close()
    {
        EnsureNotDisposed();
        EnsureFeature(NativeWebViewFeature.Dialog, nameof(Close));

        if (!_isVisible && _gtkWindow == IntPtr.Zero)
        {
            return;
        }

        if (OperatingSystem.IsLinux())
        {
            DestroyWindowCore();
            return;
        }

        NotifyClosed();
    }

    public void Move(double left, double top)
    {
        EnsureNotDisposed();
        EnsureFeature(NativeWebViewFeature.Dialog, nameof(Move));

        if (!OperatingSystem.IsLinux() || _gtkWindow == IntPtr.Zero)
        {
            return;
        }

        LinuxGtkDispatcher.InvokeAsync(
            () => LinuxNativeInterop.gtk_window_move(_gtkWindow, RoundToInt(left), RoundToInt(top)),
            CancellationToken.None).GetAwaiter().GetResult();
    }

    public void Resize(double width, double height)
    {
        EnsureNotDisposed();
        EnsureFeature(NativeWebViewFeature.Dialog, nameof(Resize));

        if (width <= 0 || height <= 0)
        {
            throw new ArgumentOutOfRangeException(nameof(width), "Dialog size must be greater than zero.");
        }

        if (!OperatingSystem.IsLinux() || _gtkWindow == IntPtr.Zero)
        {
            return;
        }

        LinuxGtkDispatcher.InvokeAsync(
            () => LinuxNativeInterop.gtk_window_resize(_gtkWindow, RoundToInt(width), RoundToInt(height)),
            CancellationToken.None).GetAwaiter().GetResult();
    }

    public void Navigate(string url)
    {
        EnsureNotDisposed();
        _backend.Navigate(url);
    }

    public void Navigate(Uri uri)
    {
        EnsureNotDisposed();
        _backend.Navigate(uri);
    }

    public void Reload()
    {
        EnsureNotDisposed();
        _backend.Reload();
    }

    public void Stop()
    {
        EnsureNotDisposed();
        _backend.Stop();
    }

    public void GoBack()
    {
        EnsureNotDisposed();
        _backend.GoBack();
    }

    public void GoForward()
    {
        EnsureNotDisposed();
        _backend.GoForward();
    }

    public Task<string?> ExecuteScriptAsync(string script, CancellationToken cancellationToken = default)
    {
        EnsureNotDisposed();
        return _backend.ExecuteScriptAsync(script, cancellationToken);
    }

    public Task PostWebMessageAsJsonAsync(string message, CancellationToken cancellationToken = default)
    {
        EnsureNotDisposed();
        return _backend.PostWebMessageAsJsonAsync(message, cancellationToken);
    }

    public Task PostWebMessageAsStringAsync(string message, CancellationToken cancellationToken = default)
    {
        EnsureNotDisposed();
        return _backend.PostWebMessageAsStringAsync(message, cancellationToken);
    }

    public void OpenDevToolsWindow()
    {
        EnsureNotDisposed();
        _backend.OpenDevToolsWindow();
    }

    public Task<NativeWebViewPrintResult> PrintAsync(NativeWebViewPrintSettings? settings = null, CancellationToken cancellationToken = default)
    {
        EnsureNotDisposed();
        return _backend.PrintAsync(settings, cancellationToken);
    }

    public Task<bool> ShowPrintUiAsync(CancellationToken cancellationToken = default)
    {
        EnsureNotDisposed();
        return _backend.ShowPrintUiAsync(cancellationToken);
    }

    public void SetZoomFactor(double zoomFactor)
    {
        EnsureNotDisposed();
        _backend.SetZoomFactor(zoomFactor);
    }

    public void SetUserAgent(string? userAgent)
    {
        EnsureNotDisposed();
        _backend.SetUserAgent(userAgent);
    }

    public void SetHeader(string? header)
    {
        EnsureNotDisposed();
        _backend.SetHeader(header);
    }

    public bool TryGetDownloadManager(out INativeWebViewDownloadManager? downloadManager)
    {
        EnsureNotDisposed();
        return _backend.TryGetDownloadManager(out downloadManager);
    }

    public bool TryGetPlatformHandle(out NativePlatformHandle handle)
    {
        handle = _gtkWindow != IntPtr.Zero
            ? new NativePlatformHandle(_gtkWindow, "GtkWindow")
            : PlaceholderPlatformHandle;
        return true;
    }

    public bool TryGetDialogHandle(out NativePlatformHandle handle)
    {
        if (_backend is INativeWebViewPlatformHandleProvider provider &&
            provider.TryGetViewHandle(out handle))
        {
            return true;
        }

        handle = PlaceholderDialogHandle;
        return true;
    }

    public bool TryGetHostWindowHandle(out NativePlatformHandle handle)
    {
        handle = _windowXid != IntPtr.Zero
            ? new NativePlatformHandle(_windowXid, "XID")
            : PlaceholderHostWindowHandle;
        return true;
    }

    public void Dispose()
    {
        if (_disposed)
        {
            return;
        }

        _disposed = true;

        try
        {
            DestroyWindowCore();
        }
        catch
        {
            // Best-effort cleanup for native resources.
        }

        _backend.NavigationStarted -= OnNavigationStarted;
        _backend.NavigationCompleted -= OnNavigationCompleted;
        _backend.WebMessageReceived -= OnWebMessageReceived;
        _backend.NewWindowRequested -= OnNewWindowRequested;
        _backend.WebResourceRequested -= OnWebResourceRequested;
        _backend.ContextMenuRequested -= OnContextMenuRequested;
        _backend.DestroyRequested -= OnDestroyRequested;
        _backend.ZoomFactorChanged -= OnZoomFactorChanged;
        _backend.Dispose();
    }

    private void OnZoomFactorChanged(object? sender, NativeWebViewZoomFactorChangedEventArgs e)
    {
        _ = sender;
        ZoomFactorChanged?.Invoke(this, e);
    }

    [SupportedOSPlatform("linux")]
    private void EnsureWindowCreated()
    {
        if (_gtkWindow != IntPtr.Zero)
        {
            return;
        }

        var hostWindow = LinuxGtkDispatcher.InvokeAsync(
            CreateWindowOnGtkThread,
            CancellationToken.None).GetAwaiter().GetResult();

        _gtkWindow = hostWindow.GtkWindow;
        _windowXid = hostWindow.Xid;
        _backend.AttachToNativeParent(new NativePlatformHandle(_gtkWindow, "GtkWindow"));
    }

    [SupportedOSPlatform("linux")]
    private LinuxHostWindowHandle CreateWindowOnGtkThread()
    {
        var gtkWindow = LinuxNativeInterop.gtk_window_new(LinuxNativeInterop.GtkWindowType.TopLevel);
        if (gtkWindow == IntPtr.Zero)
        {
            throw new InvalidOperationException("Unable to create the GTK dialog host window.");
        }

        LinuxNativeInterop.gtk_window_set_resizable(gtkWindow, true);
        LinuxNativeInterop.gtk_window_resize(gtkWindow, 900, 700);
        LinuxNativeInterop.gtk_widget_realize(gtkWindow);

        _windowSignalSubscriptions.Add(
            LinuxNativeInterop.ConnectSignal(
                gtkWindow,
                "delete-event",
                new LinuxNativeInterop.DeleteEventSignal(OnDeleteEvent)));
        _windowSignalSubscriptions.Add(
            LinuxNativeInterop.ConnectSignal(
                gtkWindow,
                "destroy",
                new LinuxNativeInterop.CloseSignal(OnWindowDestroyed)));

        var gdkWindow = LinuxNativeInterop.gtk_widget_get_window(gtkWindow);
        if (gdkWindow == IntPtr.Zero)
        {
            foreach (var subscription in _windowSignalSubscriptions)
            {
                subscription.Dispose();
            }

            _windowSignalSubscriptions.Clear();
            LinuxNativeInterop.gtk_widget_destroy(gtkWindow);
            throw new InvalidOperationException("GTK did not expose a realized GDK window for the Linux dialog host.");
        }

        var xid = LinuxNativeInterop.gdk_x11_window_get_xid(gdkWindow);
        if (xid == IntPtr.Zero)
        {
            foreach (var subscription in _windowSignalSubscriptions)
            {
                subscription.Dispose();
            }

            _windowSignalSubscriptions.Clear();
            LinuxNativeInterop.gtk_widget_destroy(gtkWindow);
            throw new InvalidOperationException("GTK did not expose an X11 window for the Linux dialog host.");
        }

        return new LinuxHostWindowHandle(gtkWindow, xid);
    }

    private void ApplyWindowOptionsOnGtkThread(NativeWebDialogShowOptions? options)
    {
        if (!OperatingSystem.IsLinux())
        {
            return;
        }

        if (_gtkWindow == IntPtr.Zero)
        {
            return;
        }

        options ??= new NativeWebDialogShowOptions();

        LinuxNativeInterop.gtk_window_set_title(
            _gtkWindow,
            string.IsNullOrWhiteSpace(options.Title) ? "Authentication" : options.Title);
        LinuxNativeInterop.gtk_window_resize(
            _gtkWindow,
            RoundToInt(options.Width),
            RoundToInt(options.Height));

        if (!options.CenterOnParent)
        {
            LinuxNativeInterop.gtk_window_move(
                _gtkWindow,
                RoundToInt(options.Left),
                RoundToInt(options.Top));
        }

        LinuxNativeInterop.gtk_widget_show_all(_gtkWindow);
        LinuxNativeInterop.gtk_window_present(_gtkWindow);
    }

    private void DestroyWindowCore()
    {
        var hadWindow = _gtkWindow != IntPtr.Zero;

        if (hadWindow && OperatingSystem.IsLinux())
        {
            _suppressDestroyNotification = true;

            try
            {
                foreach (var subscription in _windowSignalSubscriptions)
                {
                    subscription.Dispose();
                }

                _windowSignalSubscriptions.Clear();
                _backend.DetachFromNativeParent();

                var gtkWindow = _gtkWindow;
                LinuxGtkDispatcher.InvokeAsync(
                    () => LinuxNativeInterop.gtk_widget_destroy(gtkWindow),
                    CancellationToken.None).GetAwaiter().GetResult();
            }
            finally
            {
                _gtkWindow = IntPtr.Zero;
                _windowXid = IntPtr.Zero;
                _suppressDestroyNotification = false;
            }
        }

        NotifyClosed();
    }

    private int OnDeleteEvent(IntPtr widget, IntPtr eventHandle, IntPtr userData)
    {
        _ = widget;
        _ = eventHandle;
        _ = userData;

        Close();
        return 1;
    }

    private void OnWindowDestroyed(IntPtr widget, IntPtr userData)
    {
        _ = widget;
        _ = userData;

        if (_suppressDestroyNotification)
        {
            return;
        }

        try
        {
            _backend.DetachFromNativeParent();
        }
        catch
        {
            // Native teardown is already in progress.
        }

        foreach (var subscription in _windowSignalSubscriptions)
        {
            subscription.Dispose();
        }

        _windowSignalSubscriptions.Clear();
        _gtkWindow = IntPtr.Zero;
        _windowXid = IntPtr.Zero;
        NotifyClosed();
    }

    private void NotifyClosed()
    {
        if (!_isVisible)
        {
            return;
        }

        _isVisible = false;
        Closed?.Invoke(this, EventArgs.Empty);
    }

    private void OnNavigationStarted(object? sender, NativeWebViewNavigationStartedEventArgs e)
    {
        _ = sender;
        NavigationStarted?.Invoke(this, e);
    }

    private void OnNavigationCompleted(object? sender, NativeWebViewNavigationCompletedEventArgs e)
    {
        _ = sender;
        NavigationCompleted?.Invoke(this, e);
    }

    private void OnWebMessageReceived(object? sender, NativeWebViewMessageReceivedEventArgs e)
    {
        _ = sender;
        WebMessageReceived?.Invoke(this, e);
    }

    private void OnNewWindowRequested(object? sender, NativeWebViewNewWindowRequestedEventArgs e)
    {
        _ = sender;
        NewWindowRequested?.Invoke(this, e);
    }

    private void OnWebResourceRequested(object? sender, NativeWebViewResourceRequestedEventArgs e)
    {
        _ = sender;
        WebResourceRequested?.Invoke(this, e);
    }

    private void OnContextMenuRequested(object? sender, NativeWebViewContextMenuRequestedEventArgs e)
    {
        _ = sender;
        ContextMenuRequested?.Invoke(this, e);
    }

    private void OnDestroyRequested(object? sender, NativeWebViewDestroyRequestedEventArgs e)
    {
        _ = sender;
        _ = e;

        if (_isVisible)
        {
            Close();
        }
    }

    private void EnsureNotDisposed()
    {
        ObjectDisposedException.ThrowIf(_disposed, this);
    }

    private void EnsureFeature(NativeWebViewFeature feature, string operation)
    {
        if (!Features.Supports(feature))
        {
            throw new NotSupportedException($"{operation} is not supported on platform '{Platform}'.");
        }
    }

    private static int RoundToInt(double value)
    {
        return Math.Max(1, (int)Math.Round(value, MidpointRounding.AwayFromZero));
    }

    private readonly record struct LinuxHostWindowHandle(nint GtkWindow, nint Xid);
}
