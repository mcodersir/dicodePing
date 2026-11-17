using System.Runtime.Versioning;
using System.Text.Json;
using NativeWebView.Core;
using NativeWebView.Interop;

namespace NativeWebView.Platform.Linux;

public sealed class LinuxNativeWebViewBackend
    : INativeWebViewBackend,
      INativeWebViewFrameSource,
      INativeWebViewPlatformHandleProvider,
      INativeWebViewInstanceConfigurationTarget,
      INativeWebViewNativeControlAttachment,
      INativeWebViewFaviconProvider,
      INativeWebViewSnapshotProvider,
      INativeWebViewStatusTextProvider,
      INativeWebViewZoomFactorProvider,
      INativeWebViewContextMenuBackend
{
    private static readonly NativePlatformHandle PlaceholderPlatformHandle = new(0x3001, "XID");
    private static readonly NativePlatformHandle PlaceholderViewHandle = new(0x3002, "WebKitWebView");
    private static readonly NativePlatformHandle PlaceholderControllerHandle = new(0x3003, "WebKitSettings");
    private const string ScriptMessageHandlerName = "nativewebview";

    private static readonly string JavaScriptBridgeSource = """
        (() => {
          const chromeRoot = window.chrome = window.chrome || {};
          const webview = chromeRoot.webview = chromeRoot.webview || {};
          const listeners = webview.__listeners = webview.__listeners || [];

          webview.postMessage = (message) => {
            const handler = window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.nativewebview;
            if (handler && typeof handler.postMessage === 'function') {
              handler.postMessage(message);
            }
          };

          webview.addEventListener = (type, listener) => {
            if (type !== 'message' || typeof listener !== 'function' || listeners.includes(listener)) {
              return;
            }

            listeners.push(listener);
          };

          webview.removeEventListener = (type, listener) => {
            if (type !== 'message') {
              return;
            }

            const index = listeners.indexOf(listener);
            if (index >= 0) {
              listeners.splice(index, 1);
            }
          };

          webview.__dispatchMessage = (message) => {
            const event = { data: message };
            for (const listener of [...listeners]) {
              try {
                listener(event);
              } catch (error) {
                console.error(error);
              }
            }

            window.dispatchEvent(new MessageEvent('message', { data: message }));
            return true;
          };
        })();
        """;

    private readonly SemaphoreSlim _runtimeGate = new(1, 1);
    private readonly SemaphoreSlim _programmaticDownloadGate = new(1, 1);
    private readonly List<Uri> _history = [];
    private readonly List<IDisposable> _signalSubscriptions = [];
    private readonly List<IDisposable> _contextMenuActionSubscriptions = [];
    private readonly Dictionary<IntPtr, (string CommandId, NativeWebViewContextMenuTarget Target)> _contextMenuActions = [];
    private readonly INativeWebViewCommandManager _commandManager = NativeWebViewBackendSupport.NoopCommandManagerInstance;
    private readonly INativeWebViewCookieManager _cookieManager = NativeWebViewBackendSupport.NoopCookieManagerInstance;
    private readonly NativeWebViewDownloadManager _downloadManager;
    private readonly Dictionary<IntPtr, NativeWebViewDownloadManager.NativeWebViewDownloadItem> _downloadItems = [];
    private readonly Dictionary<IntPtr, Uri> _downloadUris = [];
    private readonly Lock _pendingDownloadGate = new();
    private readonly RuntimeNavigationReplayState _navigationReplayState = new();
    private readonly LinuxRuntimeNavigationLifecycle _runtimeNavigationLifecycle = new();
    private readonly List<PendingProgrammaticDownload> _pendingProgrammaticDownloads = [];

    private TaskCompletionSource<bool> _attachmentTcs = CreatePendingAttachmentSource();
    private NativeWebViewInstanceConfiguration _instanceConfiguration = new();

    private NativeWebViewEnvironmentOptions? _preparedEnvironmentOptions;
    private NativeWebViewControllerOptions? _preparedControllerOptions;

    private Uri? _currentUrl;

    private nint _parentWindowXid;
    private nint _gtkWindow;
    private nint _hostWindowXid;
    private nint _webView;
    private nint _settings;
    private nint _webContext;
    private nint _websiteDataManager;
    private nint _userContentManager;

    private int _historyIndex = -1;
    private long _frameSequence;

    private bool _isStubInitialized;
    private bool _isRuntimeInitialized;
    private bool _coreInitializedRaised;
    private bool _runtimeInitializationRequested;
    private bool _ownsGtkWindow;
    private bool _disposed;
    private int _disposeState;

    private bool _canGoBack;
    private bool _canGoForward;
    private bool _isDevToolsEnabled;
    private bool _isContextMenuEnabled;
    private bool _isStatusBarEnabled;
    private bool _isZoomControlEnabled;

    private double _zoomFactor;
    private string? _headerString;
    private string? _userAgentString;
    private Uri? _faviconUri;
    private int _faviconRefreshVersion;
    private int _snapshotGeneration;
    private string? _activeContextMenuTargetToken;
    private string? _statusText;

    public LinuxNativeWebViewBackend()
    {
        Platform = NativeWebViewPlatform.Linux;
        Features = LinuxPlatformFeatures.Instance;
        _downloadManager = new NativeWebViewDownloadManager(StartDownloadAsyncCore);
        _zoomFactor = 1.0;
        _isDevToolsEnabled = Features.Supports(NativeWebViewFeature.DevTools);
        _isContextMenuEnabled = Features.Supports(NativeWebViewFeature.ContextMenu);
        _isStatusBarEnabled = Features.Supports(NativeWebViewFeature.StatusBar);
        _isZoomControlEnabled = Features.Supports(NativeWebViewFeature.ZoomControl);
    }

    public NativeWebViewPlatform Platform { get; }

    public IWebViewPlatformFeatures Features { get; }

    public Uri? CurrentUrl => _currentUrl;

    public bool IsInitialized => _isRuntimeInitialized || _isStubInitialized;

    public bool CanGoBack => _canGoBack;

    public bool CanGoForward => _canGoForward;

    public bool IsDevToolsEnabled
    {
        get => _isDevToolsEnabled;
        set
        {
            EnsureNotDisposed();
            _isDevToolsEnabled = value;
            _ = ApplyRuntimeSettingsAsync();
        }
    }

    public bool IsContextMenuEnabled
    {
        get => _isContextMenuEnabled;
        set
        {
            EnsureNotDisposed();
            _isContextMenuEnabled = value;
        }
    }

    public bool IsStatusBarEnabled
    {
        get => _isStatusBarEnabled;
        set
        {
            EnsureNotDisposed();
            _isStatusBarEnabled = value;
        }
    }

    public bool IsZoomControlEnabled
    {
        get => _isZoomControlEnabled;
        set
        {
            EnsureNotDisposed();
            _isZoomControlEnabled = value;
        }
    }

    public double ZoomFactor => _zoomFactor;

    public string? HeaderString => _headerString;

    public string? UserAgentString => _userAgentString;

    public string? StatusText => _statusText;

    public event EventHandler<CoreWebViewInitializedEventArgs>? CoreWebView2Initialized;

    public event EventHandler<NativeWebViewNavigationStartedEventArgs>? NavigationStarted;

    public event EventHandler<NativeWebViewNavigationCompletedEventArgs>? NavigationCompleted;

    public event EventHandler<NativeWebViewMessageReceivedEventArgs>? WebMessageReceived;

    public event EventHandler<NativeWebViewOpenDevToolsRequestedEventArgs>? OpenDevToolsRequested;

    public event EventHandler<NativeWebViewDestroyRequestedEventArgs>? DestroyRequested;

#pragma warning disable CS0067
    public event EventHandler<NativeWebViewRequestCustomChromeEventArgs>? RequestCustomChrome;

    public event EventHandler<NativeWebViewRequestParentWindowPositionEventArgs>? RequestParentWindowPosition;

    public event EventHandler<NativeWebViewBeginMoveDragEventArgs>? BeginMoveDrag;

    public event EventHandler<NativeWebViewBeginResizeDragEventArgs>? BeginResizeDrag;
#pragma warning restore CS0067

    public event EventHandler<NativeWebViewNewWindowRequestedEventArgs>? NewWindowRequested;

    public event EventHandler<NativeWebViewResourceRequestedEventArgs>? WebResourceRequested;

    public event EventHandler<NativeWebViewContextMenuRequestedEventArgs>? ContextMenuRequested;

    public event EventHandler<NativeWebViewContextMenuCommandInvokedEventArgs>? ContextMenuCommandInvoked;

    public event EventHandler<NativeWebViewStatusTextChangedEventArgs>? StatusTextChanged;

    public event EventHandler<NativeWebViewZoomFactorChangedEventArgs>? ZoomFactorChanged;

    public event EventHandler<NativeWebViewNavigationHistoryChangedEventArgs>? NavigationHistoryChanged;

    public event EventHandler<CoreWebViewEnvironmentRequestedEventArgs>? CoreWebView2EnvironmentRequested;

    public event EventHandler<CoreWebViewControllerOptionsRequestedEventArgs>? CoreWebView2ControllerOptionsRequested;

    public event EventHandler<NativeWebViewFaviconChangedEventArgs>? FaviconChanged;

    public void ApplyInstanceConfiguration(NativeWebViewInstanceConfiguration configuration)
    {
        ArgumentNullException.ThrowIfNull(configuration);
        NativeWebViewProxyPlatformSupportMatrix.ValidateNoProxy(Platform, configuration.EnvironmentOptions.Proxy);
        EnsureNotDisposed();

        _instanceConfiguration = configuration.Clone();
        if (!_coreInitializedRaised)
        {
            _preparedEnvironmentOptions = null;
            _preparedControllerOptions = null;
        }
    }

    public async ValueTask InitializeAsync(CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        EnsureNotDisposed();
        EnsureFeature(NativeWebViewFeature.EmbeddedView, nameof(InitializeAsync));

        if (OperatingSystem.IsLinux())
        {
            _runtimeInitializationRequested = true;

            if (_hostWindowXid != IntPtr.Zero)
            {
                await EnsureRuntimeInitializedAsync(cancellationToken).ConfigureAwait(false);
                return;
            }
        }

        EnsureStubInitialized();
    }

    public void Navigate(string url)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(url);

        if (!Uri.TryCreate(url, UriKind.RelativeOrAbsolute, out var uri))
        {
            throw new ArgumentException($"Invalid URL: {url}", nameof(url));
        }

        Navigate(uri);
    }

    public void Navigate(Uri uri)
    {
        ArgumentNullException.ThrowIfNull(uri);
        EnsureNotDisposed();
        EnsureFeature(NativeWebViewFeature.EmbeddedView, nameof(Navigate));

        if (ShouldUseRuntimePath())
        {
            _runtimeInitializationRequested = true;
            var navigation = SetPendingRuntimeNavigation(uri);
            if (navigation.IsRuntimeReady)
            {
                ScheduleRuntimeNavigation(navigation);
            }
            else
            {
                _ = TryInitializeRuntimeInBackgroundAsync();
            }

            return;
        }

        if (OperatingSystem.IsLinux())
        {
            _currentUrl = uri;
            _ = _navigationReplayState.SetRequested(uri, isRuntimeReady: false);
            _runtimeInitializationRequested = true;
            return;
        }

        NavigateFallback(uri);
    }

    public void Reload()
    {
        EnsureNotDisposed();
        EnsureFeature(NativeWebViewFeature.EmbeddedView, nameof(Reload));

        if (ShouldUseRuntimePath())
        {
            if (IsRuntimeReady())
            {
                _ = LinuxGtkDispatcher.InvokeAsync(() => LinuxNativeInterop.webkit_web_view_reload(_webView));
            }
            else if (_currentUrl is not null)
            {
                _ = SetPendingRuntimeNavigation(_currentUrl);
                _ = TryInitializeRuntimeInBackgroundAsync();
            }

            return;
        }

        if (_currentUrl is null)
        {
            return;
        }

        NavigationStarted?.Invoke(this, new NativeWebViewNavigationStartedEventArgs(_currentUrl, isRedirected: false));
        NavigationCompleted?.Invoke(this, new NativeWebViewNavigationCompletedEventArgs(_currentUrl, isSuccess: true, httpStatusCode: 200));
    }

    public void Stop()
    {
        EnsureNotDisposed();
        EnsureFeature(NativeWebViewFeature.EmbeddedView, nameof(Stop));

        if (IsRuntimeReady())
        {
            _ = LinuxGtkDispatcher.InvokeAsync(() => LinuxNativeInterop.webkit_web_view_stop_loading(_webView));
        }
    }

    public void GoBack()
    {
        EnsureNotDisposed();
        EnsureFeature(NativeWebViewFeature.EmbeddedView, nameof(GoBack));

        if (ShouldUseRuntimePath())
        {
            if (IsRuntimeReady())
            {
                _ = LinuxGtkDispatcher.InvokeAsync(() =>
                {
                    if (LinuxNativeInterop.webkit_web_view_can_go_back(_webView))
                    {
                        LinuxNativeInterop.webkit_web_view_go_back(_webView);
                    }
                });
            }

            return;
        }

        if (!CanGoBack)
        {
            return;
        }

        _historyIndex--;
        _currentUrl = _history[_historyIndex];
        UpdateHistorySnapshot(_historyIndex > 0, _historyIndex < _history.Count - 1);
        NavigationCompleted?.Invoke(this, new NativeWebViewNavigationCompletedEventArgs(_currentUrl, isSuccess: true, httpStatusCode: 200));
    }

    public void GoForward()
    {
        EnsureNotDisposed();
        EnsureFeature(NativeWebViewFeature.EmbeddedView, nameof(GoForward));

        if (ShouldUseRuntimePath())
        {
            if (IsRuntimeReady())
            {
                _ = LinuxGtkDispatcher.InvokeAsync(() =>
                {
                    if (LinuxNativeInterop.webkit_web_view_can_go_forward(_webView))
                    {
                        LinuxNativeInterop.webkit_web_view_go_forward(_webView);
                    }
                });
            }

            return;
        }

        if (!CanGoForward)
        {
            return;
        }

        _historyIndex++;
        _currentUrl = _history[_historyIndex];
        UpdateHistorySnapshot(_historyIndex > 0, _historyIndex < _history.Count - 1);
        NavigationCompleted?.Invoke(this, new NativeWebViewNavigationCompletedEventArgs(_currentUrl, isSuccess: true, httpStatusCode: 200));
    }

    public async Task<string?> ExecuteScriptAsync(string script, CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(script);
        cancellationToken.ThrowIfCancellationRequested();
        EnsureNotDisposed();
        EnsureFeature(NativeWebViewFeature.ScriptExecution, nameof(ExecuteScriptAsync));

        if (ShouldUseRuntimePath())
        {
            await EnsureRuntimeInitializedAsync(cancellationToken).ConfigureAwait(false);
            var execution = await LinuxGtkDispatcher.InvokeAsync(
                () => LinuxNativeInterop.RunJavaScriptAsync(_webView, script, cancellationToken),
                cancellationToken).ConfigureAwait(false);

            return await execution.ConfigureAwait(false);
        }

        EnsureStubInitialized();
        return "null";
    }

    public async Task<NativeWebViewFavicon?> GetFaviconAsync(
        NativeWebViewFaviconFormat format = NativeWebViewFaviconFormat.Original,
        CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        EnsureNotDisposed();
        EnsureFeature(NativeWebViewFeature.Favicon, nameof(GetFaviconAsync));

        if (!ShouldUseRuntimePath())
        {
            return null;
        }

        await EnsureRuntimeInitializedAsync(cancellationToken).ConfigureAwait(false);
        var faviconUri = await ResolveRuntimeFaviconUriAsync(cancellationToken).ConfigureAwait(false);
        return await NativeWebViewFaviconSupport.DownloadFaviconAsync(
            faviconUri,
            format,
            (_preparedEnvironmentOptions ?? _instanceConfiguration.EnvironmentOptions).Proxy?.NoProxy == true,
            cancellationToken).ConfigureAwait(false);
    }

    public NativeWebViewSnapshotCapture BeginCaptureSnapshot(CancellationToken cancellationToken = default)
    {
        EnsureNotDisposed();
        cancellationToken.ThrowIfCancellationRequested();
        if (!OperatingSystem.IsLinux() || !IsRuntimeReady())
            return NativeWebViewSnapshotCapture.FromResult(null);

        var generation = Volatile.Read(ref _snapshotGeneration);
        var captureStarted = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var completion = CaptureSnapshotCoreAsync(generation, captureStarted, cancellationToken);
        return new NativeWebViewSnapshotCapture(captureStarted.Task, completion);
    }

    public Task<NativeWebViewSnapshot?> CaptureSnapshotAsync(CancellationToken cancellationToken = default) =>
        BeginCaptureSnapshot(cancellationToken).Completion;

    private async Task<NativeWebViewSnapshot?> CaptureSnapshotCoreAsync(
        int generation,
        TaskCompletionSource captureStarted,
        CancellationToken cancellationToken)
    {
        try
        {
            var captureTask = await LinuxGtkDispatcher.InvokeAsync(
                () =>
                {
                    var pendingCapture = LinuxNativeInterop.CaptureSnapshotPngAsync(_webView, cancellationToken);
                    captureStarted.TrySetResult();
                    return pendingCapture;
                },
                cancellationToken).ConfigureAwait(false);
            var pngData = await captureTask.ConfigureAwait(false);
            cancellationToken.ThrowIfCancellationRequested();
            if (_disposed || generation != Volatile.Read(ref _snapshotGeneration) || pngData is not { Length: > 0 })
                return null;
            return new NativeWebViewSnapshot(pngData);
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            throw;
        }
        catch
        {
            return null;
        }
        finally
        {
            captureStarted.TrySetResult();
        }
    }

    public async Task PostWebMessageAsJsonAsync(string message, CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(message);
        cancellationToken.ThrowIfCancellationRequested();
        EnsureNotDisposed();
        EnsureFeature(NativeWebViewFeature.WebMessageChannel, nameof(PostWebMessageAsJsonAsync));
        var jsonMessage = NativeWebViewBackendSupport.NormalizeJsonMessagePayload(message);

        if (ShouldUseRuntimePath())
        {
            await EnsureRuntimeInitializedAsync(cancellationToken).ConfigureAwait(false);
            var script = BuildDispatchScript(jsonMessage);
            var execution = await LinuxGtkDispatcher.InvokeAsync(
                () => LinuxNativeInterop.RunJavaScriptAsync(_webView, script, cancellationToken),
                cancellationToken).ConfigureAwait(false);

            await execution.ConfigureAwait(false);
            return;
        }

        EnsureStubInitialized();
        WebMessageReceived?.Invoke(this, new NativeWebViewMessageReceivedEventArgs(message: null, json: jsonMessage));
    }

    public async Task PostWebMessageAsStringAsync(string message, CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(message);
        cancellationToken.ThrowIfCancellationRequested();
        EnsureNotDisposed();
        EnsureFeature(NativeWebViewFeature.WebMessageChannel, nameof(PostWebMessageAsStringAsync));

        if (ShouldUseRuntimePath())
        {
            await EnsureRuntimeInitializedAsync(cancellationToken).ConfigureAwait(false);
            var payload = JsonSerializer.Serialize(message);
            var script = BuildDispatchScript(payload);
            var execution = await LinuxGtkDispatcher.InvokeAsync(
                () => LinuxNativeInterop.RunJavaScriptAsync(_webView, script, cancellationToken),
                cancellationToken).ConfigureAwait(false);

            await execution.ConfigureAwait(false);
            return;
        }

        EnsureStubInitialized();
        WebMessageReceived?.Invoke(this, new NativeWebViewMessageReceivedEventArgs(message, json: null));
    }

    public void OpenDevToolsWindow()
    {
        EnsureNotDisposed();
        EnsureFeature(NativeWebViewFeature.DevTools, nameof(OpenDevToolsWindow));

        if (ShouldUseRuntimePath() && _webView != IntPtr.Zero && _isDevToolsEnabled)
        {
            _ = LinuxGtkDispatcher.InvokeAsync(() =>
            {
                var inspector = LinuxNativeInterop.webkit_web_view_get_inspector(_webView);
                if (inspector != IntPtr.Zero)
                {
                    LinuxNativeInterop.webkit_web_inspector_show(inspector);
                }
            });
        }

        OpenDevToolsRequested?.Invoke(this, new NativeWebViewOpenDevToolsRequestedEventArgs());
    }

    public async Task<NativeWebViewPrintResult> PrintAsync(
        NativeWebViewPrintSettings? settings = null,
        CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        EnsureNotDisposed();

        if (!Features.Supports(NativeWebViewFeature.Printing))
        {
            return new NativeWebViewPrintResult(NativeWebViewPrintStatus.NotSupported);
        }

        if (ShouldUseRuntimePath())
        {
            await EnsureRuntimeInitializedAsync(cancellationToken).ConfigureAwait(false);

            if (!string.IsNullOrWhiteSpace(settings?.OutputPath))
            {
                return new NativeWebViewPrintResult(
                    NativeWebViewPrintStatus.NotSupported,
                    "The Linux WebKitGTK backend currently supports native print delegation, but not direct PDF export.");
            }

            try
            {
                await LinuxGtkDispatcher.InvokeAsync(() =>
                {
                    var printOperation = LinuxNativeInterop.webkit_print_operation_new(_webView);
                    if (printOperation == IntPtr.Zero)
                    {
                        throw new InvalidOperationException("Unable to create a WebKitGTK print operation.");
                    }

                    try
                    {
                        LinuxNativeInterop.webkit_print_operation_print(printOperation);
                    }
                    finally
                    {
                        LinuxNativeInterop.g_object_unref(printOperation);
                    }
                }, cancellationToken).ConfigureAwait(false);

                return new NativeWebViewPrintResult(NativeWebViewPrintStatus.Success);
            }
            catch (Exception ex)
            {
                return new NativeWebViewPrintResult(NativeWebViewPrintStatus.Failed, ex.Message);
            }
        }

        EnsureStubInitialized();
        return new NativeWebViewPrintResult(NativeWebViewPrintStatus.Success);
    }

    public Task<bool> ShowPrintUiAsync(CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        EnsureNotDisposed();
        return Task.FromResult(false);
    }

    public void SetZoomFactor(double zoomFactor)
    {
        EnsureNotDisposed();

        if (!NativeWebViewZoomFactor.IsValid(zoomFactor))
        {
            throw new ArgumentOutOfRangeException(nameof(zoomFactor), zoomFactor, "Zoom factor must be finite and greater than zero.");
        }

        UpdateZoomFactor(zoomFactor);
        if (IsRuntimeReady())
        {
            _ = LinuxGtkDispatcher.InvokeAsync(() => LinuxNativeInterop.webkit_web_view_set_zoom_level(_webView, zoomFactor));
        }
    }

    public void SetUserAgent(string? userAgent)
    {
        EnsureNotDisposed();
        _userAgentString = userAgent;
        _ = ApplyRuntimeSettingsAsync();
    }

    public void SetHeader(string? header)
    {
        EnsureNotDisposed();
        _headerString = header;
    }

    public bool TryGetCommandManager(out INativeWebViewCommandManager? commandManager)
    {
        EnsureNotDisposed();

        if (Features.Supports(NativeWebViewFeature.CommandManager))
        {
            commandManager = _commandManager;
            return true;
        }

        commandManager = null;
        return false;
    }

    public bool TryGetCookieManager(out INativeWebViewCookieManager? cookieManager)
    {
        EnsureNotDisposed();

        if (Features.Supports(NativeWebViewFeature.CookieManager))
        {
            cookieManager = _cookieManager;
            return true;
        }

        cookieManager = null;
        return false;
    }

    public bool TryGetDownloadManager(out INativeWebViewDownloadManager? downloadManager)
    {
        EnsureNotDisposed();

        if (Features.Supports(NativeWebViewFeature.Downloads))
        {
            downloadManager = _downloadManager;
            return true;
        }

        downloadManager = null;
        return false;
    }

    public void MoveFocus(NativeWebViewFocusMoveDirection direction)
    {
        EnsureNotDisposed();
        EnsureFeature(NativeWebViewFeature.EmbeddedView, nameof(MoveFocus));

        if (IsRuntimeReady())
        {
            _ = LinuxGtkDispatcher.InvokeAsync(() => LinuxNativeInterop.gtk_widget_grab_focus(_webView));
        }
    }

    public bool SupportsRenderMode(NativeWebViewRenderMode renderMode)
    {
        return renderMode switch
        {
            NativeWebViewRenderMode.Embedded => Features.Supports(NativeWebViewFeature.EmbeddedView),
            NativeWebViewRenderMode.GpuSurface => Features.Supports(NativeWebViewFeature.GpuSurfaceRendering),
            NativeWebViewRenderMode.Offscreen => Features.Supports(NativeWebViewFeature.OffscreenRendering),
            _ => false,
        };
    }

    public Task<NativeWebViewRenderFrame?> CaptureFrameAsync(
        NativeWebViewRenderMode renderMode,
        NativeWebViewRenderFrameRequest request,
        CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        EnsureNotDisposed();
        ArgumentNullException.ThrowIfNull(request);

        if (renderMode == NativeWebViewRenderMode.Embedded || !SupportsRenderMode(renderMode))
        {
            return Task.FromResult<NativeWebViewRenderFrame?>(null);
        }

        return Task.FromResult<NativeWebViewRenderFrame?>(
            NativeWebViewBackendSupport.CreateSyntheticRenderFrame(
                Platform,
                _currentUrl,
                ref _frameSequence,
                renderMode,
                request.PixelWidth,
                request.PixelHeight));
    }

    public bool TryGetPlatformHandle(out NativePlatformHandle handle)
    {
        handle = _hostWindowXid != IntPtr.Zero
            ? new NativePlatformHandle(_hostWindowXid, "XID")
            : PlaceholderPlatformHandle;
        return true;
    }

    public bool TryGetViewHandle(out NativePlatformHandle handle)
    {
        handle = _webView != IntPtr.Zero
            ? new NativePlatformHandle(_webView, "WebKitWebView")
            : PlaceholderViewHandle;
        return true;
    }

    public bool TryGetControllerHandle(out NativePlatformHandle handle)
    {
        handle = _settings != IntPtr.Zero
            ? new NativePlatformHandle(_settings, "WebKitSettings")
            : PlaceholderControllerHandle;
        return true;
    }

    public NativePlatformHandle AttachToNativeParent(NativePlatformHandle parentHandle)
    {
        EnsureNotDisposed();

        if (!OperatingSystem.IsLinux())
        {
            throw new PlatformNotSupportedException("Linux native control attachment can only run on Linux.");
        }

        if (parentHandle.Handle == IntPtr.Zero)
        {
            throw new InvalidOperationException("Parent native handle is invalid.");
        }

        if (_hostWindowXid != IntPtr.Zero)
        {
            if (_parentWindowXid == parentHandle.Handle || _gtkWindow == parentHandle.Handle)
            {
                ShowPreservedHostWindow();
                return new NativePlatformHandle(_hostWindowXid, "XID");
            }

            if (string.Equals(parentHandle.HandleDescriptor, "XID", StringComparison.OrdinalIgnoreCase))
            {
                LinuxGtkDispatcher.InvokeAsync(
                    () => LinuxNativeInterop.AttachX11WindowToParent(_hostWindowXid, parentHandle.Handle),
                    CancellationToken.None).GetAwaiter().GetResult();

                _parentWindowXid = parentHandle.Handle;
                _attachmentTcs.TrySetResult(true);
                ShowPreservedHostWindow();
                return new NativePlatformHandle(_hostWindowXid, "XID");
            }

            DetachFromNativeParent(preserveRuntime: false);
        }

        LinuxHostWindowHandle hostHandle;
        if (string.Equals(parentHandle.HandleDescriptor, "XID", StringComparison.OrdinalIgnoreCase))
        {
            hostHandle = LinuxGtkDispatcher.InvokeAsync(
                CreateHostWindowOnGtkThread,
                CancellationToken.None).GetAwaiter().GetResult();

            LinuxGtkDispatcher.InvokeAsync(
                () => LinuxNativeInterop.AttachX11WindowToParent(hostHandle.Xid, parentHandle.Handle),
                CancellationToken.None).GetAwaiter().GetResult();

            _parentWindowXid = parentHandle.Handle;
            _gtkWindow = hostHandle.GtkWindow;
            _hostWindowXid = hostHandle.Xid;
            _ownsGtkWindow = true;
        }
        else if (string.Equals(parentHandle.HandleDescriptor, "GtkWindow", StringComparison.OrdinalIgnoreCase))
        {
            hostHandle = LinuxGtkDispatcher.InvokeAsync(
                () => ResolveExistingGtkWindowOnGtkThread(parentHandle.Handle),
                CancellationToken.None).GetAwaiter().GetResult();

            _parentWindowXid = hostHandle.Xid;
            _gtkWindow = hostHandle.GtkWindow;
            _hostWindowXid = hostHandle.Xid;
            _ownsGtkWindow = false;
        }
        else
        {
            throw new InvalidOperationException(
                $"Linux native control attachment requires an XID or GtkWindow parent, but received '{parentHandle.HandleDescriptor}'.");
        }

        _attachmentTcs.TrySetResult(true);

        if (_runtimeInitializationRequested)
        {
            _ = TryInitializeRuntimeInBackgroundAsync();
        }

        return new NativePlatformHandle(_hostWindowXid, "XID");
    }

    public void DetachFromNativeParent()
    {
        EnsureNotDisposed();
        DetachFromNativeParentCore(preserveRuntime: false);
    }

    public void DetachFromNativeParent(bool preserveRuntime)
    {
        EnsureNotDisposed();
        DetachFromNativeParentCore(preserveRuntime);
    }

    public void Dispose()
    {
        if (Interlocked.Exchange(ref _disposeState, 1) != 0)
        {
            return;
        }

        _disposed = true;
        try
        {
            DetachFromNativeParentCore(preserveRuntime: false);
        }
        catch
        {
            // Best-effort shutdown for native resources.
        }

        Interlocked.Increment(ref _faviconRefreshVersion);
        _preparedEnvironmentOptions = null;
        _preparedControllerOptions = null;

        DestroyRequested?.Invoke(this, new NativeWebViewDestroyRequestedEventArgs("Disposed"));
        _runtimeGate.Dispose();
        _programmaticDownloadGate.Dispose();
    }

    private void DetachFromNativeParentCore(bool preserveRuntime)
    {
        if (preserveRuntime && _hostWindowXid != IntPtr.Zero)
        {
            HidePreservedHostWindow();
            _parentWindowXid = IntPtr.Zero;
            _attachmentTcs = CreatePendingAttachmentSource();
            return;
        }

        DestroyRuntimeHost();
        _parentWindowXid = IntPtr.Zero;
        _hostWindowXid = IntPtr.Zero;
        _ownsGtkWindow = false;
        _attachmentTcs = CreatePendingAttachmentSource();
    }

    private void HidePreservedHostWindow()
    {
        if (!OperatingSystem.IsLinux() || _gtkWindow == IntPtr.Zero)
        {
            return;
        }

        LinuxGtkDispatcher.InvokeAsync(
            () => LinuxNativeInterop.gtk_widget_hide(_gtkWindow),
            CancellationToken.None).GetAwaiter().GetResult();
    }

    private void ShowPreservedHostWindow()
    {
        if (!OperatingSystem.IsLinux() || _gtkWindow == IntPtr.Zero)
        {
            return;
        }

        LinuxGtkDispatcher.InvokeAsync(
            () => LinuxNativeInterop.gtk_widget_show_all(_gtkWindow),
            CancellationToken.None).GetAwaiter().GetResult();
    }

    private void DestroyRuntimeHost()
    {
        Interlocked.Increment(ref _snapshotGeneration);
        _isRuntimeInitialized = false;
        _navigationReplayState.RuntimeDestroyed();
        try
        {
            if (!OperatingSystem.IsLinux())
            {
                _runtimeNavigationLifecycle.RuntimeDestroyed();
                _gtkWindow = IntPtr.Zero;
                _webView = IntPtr.Zero;
                _settings = IntPtr.Zero;
                _webContext = IntPtr.Zero;
                _websiteDataManager = IntPtr.Zero;
                _userContentManager = IntPtr.Zero;
                _isRuntimeInitialized = false;
                UpdateHistorySnapshot(canGoBack: false, canGoForward: false);
                return;
            }

            if (_gtkWindow == IntPtr.Zero &&
                _webContext == IntPtr.Zero &&
                _signalSubscriptions.Count == 0)
            {
                _runtimeNavigationLifecycle.RuntimeDestroyed();
                _isRuntimeInitialized = false;
                UpdateHistorySnapshot(canGoBack: false, canGoForward: false);
                return;
            }

            try
            {
                LinuxGtkDispatcher.InvokeAsync(() =>
                {
                    try
                    {
                        ClearContextMenuActions();
                        DisposeSubscriptions(_signalSubscriptions);
                        _signalSubscriptions.Clear();

                        if (_ownsGtkWindow)
                        {
                            if (_gtkWindow != IntPtr.Zero)
                            {
                                LinuxNativeInterop.gtk_widget_destroy(_gtkWindow);
                            }
                        }
                        else if (_webView != IntPtr.Zero)
                        {
                            LinuxNativeInterop.gtk_widget_destroy(_webView);
                        }

                        if (_webContext != IntPtr.Zero)
                        {
                            LinuxNativeInterop.g_object_unref(_webContext);
                        }

                        _gtkWindow = IntPtr.Zero;
                        _webView = IntPtr.Zero;
                        _settings = IntPtr.Zero;
                        _webContext = IntPtr.Zero;
                        _websiteDataManager = IntPtr.Zero;
                        _userContentManager = IntPtr.Zero;
                    }
                    finally
                    {
                        _runtimeNavigationLifecycle.RuntimeDestroyed();
                    }
                }).GetAwaiter().GetResult();
            }
            catch
            {
                _runtimeNavigationLifecycle.RuntimeDestroyed();
                _contextMenuActionSubscriptions.Clear();
                _contextMenuActions.Clear();
                _activeContextMenuTargetToken = null;
                _signalSubscriptions.Clear();
                _gtkWindow = IntPtr.Zero;
                _webView = IntPtr.Zero;
                _settings = IntPtr.Zero;
                _webContext = IntPtr.Zero;
                _websiteDataManager = IntPtr.Zero;
                _userContentManager = IntPtr.Zero;
            }

            _isRuntimeInitialized = false;
            UpdateHistorySnapshot(canGoBack: false, canGoForward: false);
        }
        finally
        {
            SetStatusText(null);
        }
    }

    private static TaskCompletionSource<bool> CreatePendingAttachmentSource()
    {
        return new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
    }

    [SupportedOSPlatform("linux")]
    private async Task TryInitializeRuntimeInBackgroundAsync()
    {
        try
        {
            await EnsureRuntimeInitializedAsync(CancellationToken.None).ConfigureAwait(false);
        }
        catch
        {
            // Explicit InitializeAsync should surface failures. Background warmup is best effort.
        }
    }

    [SupportedOSPlatform("linux")]
    private async Task EnsureRuntimeInitializedAsync(CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();

        if (IsRuntimeReady())
        {
            return;
        }

        await _runtimeGate.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            if (IsRuntimeReady())
            {
                return;
            }

            await WaitForAttachmentAsync(cancellationToken).ConfigureAwait(false);
            EnsurePreparedInitializationOptions();

            await LinuxGtkDispatcher.InvokeAsync(
                InitializeRuntimeOnGtkThread,
                cancellationToken).ConfigureAwait(false);

            var pendingNavigation = PublishRuntimeReady();
            if (pendingNavigation.Uri is not null)
            {
                await ScheduleRuntimeNavigationAsync(pendingNavigation, cancellationToken).ConfigureAwait(false);
            }
            RaiseInitializedIfNeeded(
                success: true,
                initializationException: null,
                nativeObject: new NativePlatformHandle(_webView, "WebKitWebView"));
        }
        catch (Exception ex)
        {
            try
            {
                await LinuxGtkDispatcher.InvokeAsync(
                    RollbackRuntimeInitializationOnGtkThread,
                    CancellationToken.None).ConfigureAwait(false);
            }
            catch (Exception cleanupException)
            {
                ex.Data["NativeWebView.RuntimeInitializationCleanupException"] = cleanupException;
            }

            RaiseInitializedIfNeeded(success: false, initializationException: ex, nativeObject: null);
            throw;
        }
        finally
        {
            _runtimeGate.Release();
        }
    }

    private async Task WaitForAttachmentAsync(CancellationToken cancellationToken)
    {
        if (_hostWindowXid != IntPtr.Zero)
        {
            return;
        }

        if (!cancellationToken.CanBeCanceled)
        {
            await _attachmentTcs.Task.ConfigureAwait(false);
            return;
        }

        var cancellationSource = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
        using var registration = cancellationToken.Register(
            static state => ((TaskCompletionSource<bool>)state!).TrySetResult(true),
            cancellationSource);

        var completed = await Task.WhenAny(_attachmentTcs.Task, cancellationSource.Task).ConfigureAwait(false);
        if (completed == cancellationSource.Task)
        {
            throw new OperationCanceledException(cancellationToken);
        }

        await _attachmentTcs.Task.ConfigureAwait(false);
    }

    private bool IsRuntimeReady()
    {
        return IsRuntimeReady(Volatile.Read(ref _isRuntimeInitialized), _webView != IntPtr.Zero);
    }

    internal static bool IsRuntimeReady(bool isRuntimeInitialized, bool hasWebView) =>
        isRuntimeInitialized && hasWebView;

    private PendingRuntimeNavigation SetPendingRuntimeNavigation(Uri uri)
    {
        _currentUrl = uri;
        var request = _navigationReplayState.SetRequested(uri, IsRuntimeReady());
        return new PendingRuntimeNavigation(request.Uri, request.Version, request.IsRuntimeReady);
    }

    private PendingRuntimeNavigation PublishRuntimeReady()
    {
        Volatile.Write(ref _isRuntimeInitialized, true);
        var request = _navigationReplayState.PublishRuntimeReady();
        return new PendingRuntimeNavigation(request.Uri, request.Version, request.IsRuntimeReady);
    }

    private void ScheduleRuntimeNavigation(PendingRuntimeNavigation navigation)
    {
        _ = ScheduleRuntimeNavigationAsync(navigation, CancellationToken.None);
    }

    private Task ScheduleRuntimeNavigationAsync(
        PendingRuntimeNavigation navigation,
        CancellationToken cancellationToken)
    {
        return LinuxGtkDispatcher.InvokeAsync(
            () =>
            {
                if (!IsPendingRuntimeNavigationCurrent(navigation))
                {
                    return;
                }

                LinuxNativeInterop.webkit_web_view_load_uri(
                    _webView,
                    ToNavigationString(navigation.Uri!));
            },
            cancellationToken);
    }

    private bool IsPendingRuntimeNavigationCurrent(PendingRuntimeNavigation navigation)
    {
        var request = new RuntimeNavigationRequest(
            navigation.Uri,
            navigation.Version,
            navigation.IsRuntimeReady);
        return _navigationReplayState.IsCurrent(request, _disposed, IsRuntimeReady());
    }

    private void EnsurePreparedInitializationOptions()
    {
        if (_preparedEnvironmentOptions is not null)
        {
            return;
        }

        var environmentOptions = new NativeWebViewEnvironmentOptions();
        var controllerOptions = new NativeWebViewControllerOptions();

        _instanceConfiguration.ApplyEnvironmentOptions(environmentOptions);
        _instanceConfiguration.ApplyControllerOptions(controllerOptions);

        if (Features.Supports(NativeWebViewFeature.EnvironmentOptions))
        {
            CoreWebView2EnvironmentRequested?.Invoke(this, new CoreWebViewEnvironmentRequestedEventArgs(environmentOptions));
        }

        if (Features.Supports(NativeWebViewFeature.ControllerOptions))
        {
            CoreWebView2ControllerOptionsRequested?.Invoke(this, new CoreWebViewControllerOptionsRequestedEventArgs(controllerOptions));
        }

        NativeWebViewProxyPlatformSupportMatrix.ValidateNoProxy(Platform, environmentOptions.Proxy);
        _preparedEnvironmentOptions = environmentOptions.Clone();
        _preparedControllerOptions = controllerOptions.Clone();
    }

    private void EnsureStubInitialized()
    {
        if (_isStubInitialized)
        {
            return;
        }

        EnsurePreparedInitializationOptions();
        _isStubInitialized = true;
        RaiseInitializedIfNeeded(success: true, initializationException: null, nativeObject: null);
    }

    private void RaiseInitializedIfNeeded(bool success, Exception? initializationException, object? nativeObject)
    {
        if (_coreInitializedRaised)
        {
            return;
        }

        _coreInitializedRaised = true;
        CoreWebView2Initialized?.Invoke(this, new CoreWebViewInitializedEventArgs(success, initializationException, nativeObject));
    }

    [SupportedOSPlatformGuard("linux")]
    private bool ShouldUseRuntimePath()
    {
        return OperatingSystem.IsLinux() && _hostWindowXid != IntPtr.Zero;
    }

    private void NavigateFallback(Uri uri)
    {
        EnsureStubInitialized();

        var started = new NativeWebViewNavigationStartedEventArgs(uri, isRedirected: false);
        NavigationStarted?.Invoke(this, started);
        if (started.Cancel)
        {
            return;
        }

        if (_historyIndex < _history.Count - 1)
        {
            _history.RemoveRange(_historyIndex + 1, _history.Count - _historyIndex - 1);
        }

        _history.Add(uri);
        _historyIndex = _history.Count - 1;
        _currentUrl = uri;
        _navigationReplayState.TryUpdateReached(uri);
        UpdateHistorySnapshot(_historyIndex > 0, _historyIndex < _history.Count - 1);
        NavigationCompleted?.Invoke(this, new NativeWebViewNavigationCompletedEventArgs(uri, isSuccess: true, httpStatusCode: 200));
    }

    private void UpdateHistorySnapshot(bool canGoBack, bool canGoForward)
    {
        var changed = _canGoBack != canGoBack || _canGoForward != canGoForward;
        _canGoBack = canGoBack;
        _canGoForward = canGoForward;

        if (changed)
        {
            NavigationHistoryChanged?.Invoke(this, new NativeWebViewNavigationHistoryChangedEventArgs(_canGoBack, _canGoForward));
        }
    }

    private async Task ApplyRuntimeSettingsAsync()
    {
        if (_settings == IntPtr.Zero || !OperatingSystem.IsLinux())
        {
            return;
        }

        try
        {
            await LinuxGtkDispatcher.InvokeAsync(ApplyRuntimeSettingsOnGtkThread).ConfigureAwait(false);
        }
        catch
        {
            // Runtime settings updates are best effort.
        }
    }

    internal bool IsPageJavaScriptEnabled =>
        (_preparedControllerOptions ?? _instanceConfiguration.ControllerOptions).IsJavaScriptEnabled;

    [SupportedOSPlatform("linux")]
    private void ApplyRuntimeSettingsOnGtkThread()
    {
        if (_settings == IntPtr.Zero)
        {
            return;
        }

        LinuxNativeInterop.webkit_settings_set_enable_developer_extras(_settings, _isDevToolsEnabled);
        LinuxNativeInterop.webkit_settings_set_enable_javascript(_settings, IsPageJavaScriptEnabled);
        LinuxNativeInterop.webkit_settings_set_user_agent(_settings, _userAgentString);

        if (_webView != IntPtr.Zero && _zoomFactor > 0)
        {
            LinuxNativeInterop.webkit_web_view_set_zoom_level(_webView, _zoomFactor);
        }
    }

    [SupportedOSPlatform("linux")]
    private void InitializeRuntimeOnGtkThread()
    {
        if (_gtkWindow == IntPtr.Zero)
        {
            throw new InvalidOperationException("Cannot initialize WebKitGTK without an attached GTK host window.");
        }

        if (_webView != IntPtr.Zero)
        {
            return;
        }

        var isPrivateMode = _preparedControllerOptions?.IsInPrivateModeEnabled == true;
        _webContext = CreateWebContextOnGtkThread(_preparedEnvironmentOptions, isPrivateMode);

        if (_webContext == IntPtr.Zero)
        {
            throw new InvalidOperationException("Unable to create a WebKitGTK web context.");
        }

        ApplyEnvironmentOptionsToContextOnGtkThread(_webContext, _preparedEnvironmentOptions, isPrivateMode);
        _signalSubscriptions.Add(LinuxNativeInterop.ConnectSignal(
            _webContext,
            "download-started",
            new LinuxNativeInterop.DownloadStartedSignal(OnDownloadStarted)));

        _websiteDataManager = LinuxNativeInterop.webkit_web_context_get_website_data_manager(_webContext);
        _webView = LinuxNativeInterop.webkit_web_view_new_with_context(_webContext);

        if (_webView == IntPtr.Zero)
        {
            throw new InvalidOperationException("Unable to create a WebKitGTK web view.");
        }

        _settings = LinuxNativeInterop.webkit_web_view_get_settings(_webView);
        _userContentManager = LinuxNativeInterop.webkit_web_view_get_user_content_manager(_webView);

        if (_settings == IntPtr.Zero)
        {
            throw new InvalidOperationException("Unable to access WebKitGTK settings.");
        }

        if (_userContentManager == IntPtr.Zero)
        {
            throw new InvalidOperationException("Unable to access WebKitGTK user content manager.");
        }

        if (!LinuxNativeInterop.webkit_user_content_manager_register_script_message_handler(_userContentManager, ScriptMessageHandlerName))
        {
            throw new InvalidOperationException("Unable to register the WebKitGTK script message handler.");
        }

        var bridgeScript = LinuxNativeInterop.webkit_user_script_new(
            JavaScriptBridgeSource,
            LinuxNativeInterop.WebKitUserContentInjectedFrames.AllFrames,
            LinuxNativeInterop.WebKitUserScriptInjectionTime.DocumentStart,
            IntPtr.Zero,
            IntPtr.Zero);

        if (bridgeScript != IntPtr.Zero)
        {
            try
            {
                LinuxNativeInterop.webkit_user_content_manager_add_script(_userContentManager, bridgeScript);
            }
            finally
            {
                LinuxNativeInterop.webkit_user_script_unref(bridgeScript);
            }
        }

        foreach (var documentStartScript in _instanceConfiguration.DocumentStartScripts)
        {
            var frameScope = documentStartScript.FrameScope == NativeWebViewScriptFrameScope.MainFrame
                ? LinuxNativeInterop.WebKitUserContentInjectedFrames.TopFrame
                : LinuxNativeInterop.WebKitUserContentInjectedFrames.AllFrames;
            var script = LinuxNativeInterop.webkit_user_script_new(
                documentStartScript.Source,
                frameScope,
                LinuxNativeInterop.WebKitUserScriptInjectionTime.DocumentStart,
                IntPtr.Zero,
                IntPtr.Zero);
            if (script == IntPtr.Zero)
                throw new InvalidOperationException("WebKitGTK did not register a requested document-start script.");
            try
            {
                LinuxNativeInterop.webkit_user_content_manager_add_script(_userContentManager, script);
            }
            finally
            {
                LinuxNativeInterop.webkit_user_script_unref(script);
            }
        }

        _signalSubscriptions.Add(LinuxNativeInterop.ConnectSignal(_webView, "load-changed", new LinuxNativeInterop.LoadChangedSignal(OnLoadChanged)));
        _signalSubscriptions.Add(LinuxNativeInterop.ConnectSignal(_webView, "load-failed", new LinuxNativeInterop.LoadFailedSignal(OnLoadFailed)));
        _signalSubscriptions.Add(LinuxNativeInterop.ConnectSignal(_webView, "decide-policy", new LinuxNativeInterop.DecidePolicySignal(OnDecidePolicy)));
        _signalSubscriptions.Add(LinuxNativeInterop.ConnectSignal(_webView, "close", new LinuxNativeInterop.CloseSignal(OnCloseRequested)));
        _signalSubscriptions.Add(LinuxNativeInterop.ConnectSignal(_webView, "context-menu", new LinuxNativeInterop.ContextMenuSignal(OnContextMenu)));
        _signalSubscriptions.Add(LinuxNativeInterop.ConnectSignal(_webView, "mouse-target-changed", new LinuxNativeInterop.MouseTargetChangedSignal(OnMouseTargetChanged)));
        _signalSubscriptions.Add(LinuxNativeInterop.ConnectSignal(_webView, "notify::zoom-level", new LinuxNativeInterop.NotifySignal(OnZoomLevelChanged)));
        _signalSubscriptions.Add(LinuxNativeInterop.ConnectSignal(_userContentManager, $"script-message-received::{ScriptMessageHandlerName}", new LinuxNativeInterop.ScriptMessageReceivedSignal(OnScriptMessageReceived)));

        LinuxNativeInterop.gtk_container_add(_gtkWindow, _webView);
        LinuxNativeInterop.gtk_widget_show_all(_gtkWindow);
        ApplyRuntimeSettingsOnGtkThread();
        SyncNavigationSnapshotFromRuntimeOnGtkThread(updatePendingNavigation: false);

    }

    [SupportedOSPlatform("linux")]
    private static nint CreateWebContextOnGtkThread(
        NativeWebViewEnvironmentOptions? options,
        bool isPrivateMode)
    {
        if (isPrivateMode)
            return LinuxNativeInterop.webkit_web_context_new_ephemeral();

        var storage = ResolvePersistentStorageConfiguration(options);
        if (storage is null)
            return LinuxNativeInterop.webkit_web_context_new();

        if (storage.BaseDataDirectory is not null)
            Directory.CreateDirectory(storage.BaseDataDirectory);
        if (storage.BaseCacheDirectory is not null)
            Directory.CreateDirectory(storage.BaseCacheDirectory);

        nint websiteDataManager;
        if (storage is { BaseDataDirectory: not null, BaseCacheDirectory: not null })
        {
            websiteDataManager = LinuxNativeInterop.webkit_website_data_manager_new_with_two_directories(
                "base-data-directory",
                storage.BaseDataDirectory,
                "base-cache-directory",
                storage.BaseCacheDirectory,
                IntPtr.Zero);
        }
        else if (storage.BaseDataDirectory is not null)
        {
            websiteDataManager = LinuxNativeInterop.webkit_website_data_manager_new_with_one_directory(
                "base-data-directory",
                storage.BaseDataDirectory,
                IntPtr.Zero);
        }
        else
        {
            websiteDataManager = LinuxNativeInterop.webkit_website_data_manager_new_with_one_directory(
                "base-cache-directory",
                storage.BaseCacheDirectory!,
                IntPtr.Zero);
        }

        if (websiteDataManager == IntPtr.Zero)
            throw new InvalidOperationException("Unable to create a persistent WebKitGTK website data manager.");

        try
        {
            return LinuxNativeInterop.webkit_web_context_new_with_website_data_manager(websiteDataManager);
        }
        finally
        {
            LinuxNativeInterop.g_object_unref(websiteDataManager);
        }
    }

    internal static LinuxPersistentStorageConfiguration? ResolvePersistentStorageConfiguration(
        NativeWebViewEnvironmentOptions? options)
    {
        if (options is null)
            return null;

        var baseDataDirectory = NormalizeStorageDirectory(options.UserDataFolder) ??
                                NormalizeStorageDirectory(options.SessionDataFolder);
        var baseCacheDirectory = NormalizeStorageDirectory(options.CacheFolder);
        return baseDataDirectory is null && baseCacheDirectory is null
            ? null
            : new LinuxPersistentStorageConfiguration(baseDataDirectory, baseCacheDirectory);
    }

    private static string? NormalizeStorageDirectory(string? path) =>
        string.IsNullOrWhiteSpace(path) ? null : Path.GetFullPath(path);

    [SupportedOSPlatform("linux")]
    private void RollbackRuntimeInitializationOnGtkThread()
    {
        Volatile.Write(ref _isRuntimeInitialized, false);
        _navigationReplayState.RuntimeDestroyed();
        _runtimeNavigationLifecycle.RuntimeDestroyed();

        try
        {
            ClearContextMenuActions();
        }
        catch
        {
            _contextMenuActionSubscriptions.Clear();
            _contextMenuActions.Clear();
            _activeContextMenuTargetToken = null;
        }

        DisposeSubscriptions(_signalSubscriptions);
        _signalSubscriptions.Clear();

        if (_webView != IntPtr.Zero)
        {
            try
            {
                LinuxNativeInterop.gtk_widget_destroy(_webView);
            }
            catch
            {
                // Continue releasing the remaining partially initialized resources.
            }
        }

        if (_webContext != IntPtr.Zero)
        {
            try
            {
                LinuxNativeInterop.g_object_unref(_webContext);
            }
            catch
            {
                // Continue clearing managed references after a native cleanup failure.
            }
        }

        _webView = IntPtr.Zero;
        _settings = IntPtr.Zero;
        _webContext = IntPtr.Zero;
        _websiteDataManager = IntPtr.Zero;
        _userContentManager = IntPtr.Zero;

        try
        {
            SetStatusText(null);
        }
        catch
        {
            // Rollback must not replace the initialization failure with a subscriber exception.
        }
    }

    [SupportedOSPlatform("linux")]
    private void ApplyEnvironmentOptionsToContextOnGtkThread(
        nint webContext,
        NativeWebViewEnvironmentOptions? options,
        bool isPrivateMode)
    {
        options ??= new NativeWebViewEnvironmentOptions();

        if (!string.IsNullOrWhiteSpace(options.Language))
        {
            var languages = ParsePreferredLanguages(options.Language);
            if (languages.Count > 0)
            {
                using var languagePointers = new LinuxUtf8StringArray(languages);
                LinuxNativeInterop.webkit_web_context_set_preferred_languages(webContext, languagePointers.Pointer);
            }
        }

        var websiteDataManager = LinuxNativeInterop.webkit_web_context_get_website_data_manager(webContext);
        if (websiteDataManager == IntPtr.Zero)
        {
            if (options.Proxy?.NoProxy == true)
                throw new InvalidOperationException("WebKitGTK did not provide a website data manager for NoProxy.");
            return;
        }

        if (Features.Supports(NativeWebViewFeature.ProxyConfiguration))
        {
            var proxySettings = NativeWebViewLinuxProxySettingsBuilder.Build(options.Proxy);
            if (proxySettings?.NoProxy == true)
            {
                LinuxNativeInterop.webkit_website_data_manager_set_network_proxy_settings(
                    websiteDataManager, LinuxNativeInterop.WebKitNetworkProxyMode.NoProxy, IntPtr.Zero);
            }
            else if (proxySettings is not null)
            {
                using var ignoreHosts = new LinuxUtf8StringArray(proxySettings.IgnoreHosts);
                var nativeProxySettings = LinuxNativeInterop.webkit_network_proxy_settings_new(
                    proxySettings.DefaultProxyUri,
                    ignoreHosts.Pointer);

                try
                {
                    LinuxNativeInterop.webkit_website_data_manager_set_network_proxy_settings(
                        websiteDataManager,
                        LinuxNativeInterop.WebKitNetworkProxyMode.Custom,
                        nativeProxySettings);
                }
                finally
                {
                    if (nativeProxySettings != IntPtr.Zero)
                    {
                        LinuxNativeInterop.webkit_network_proxy_settings_free(nativeProxySettings);
                    }
                }
            }
        }

        if (!isPrivateMode && !string.IsNullOrWhiteSpace(options.CookieDataFolder))
        {
            var cookieStoragePath = ResolveCookieStoragePath(options.CookieDataFolder);
            var cookieDirectory = Path.GetDirectoryName(cookieStoragePath);
            if (!string.IsNullOrWhiteSpace(cookieDirectory))
            {
                Directory.CreateDirectory(cookieDirectory);
            }

            var cookieManager = LinuxNativeInterop.webkit_website_data_manager_get_cookie_manager(websiteDataManager);
            if (cookieManager != IntPtr.Zero)
            {
                LinuxNativeInterop.webkit_cookie_manager_set_persistent_storage(
                    cookieManager,
                    cookieStoragePath,
                    LinuxNativeInterop.WebKitCookiePersistentStorage.Sqlite);
            }
        }
    }

    [SupportedOSPlatform("linux")]
    private void SyncNavigationSnapshotFromRuntimeOnGtkThread(bool updatePendingNavigation = true)
    {
        _currentUrl = TryCreateUri(LinuxNativeInterop.ConvertUtf8Pointer(LinuxNativeInterop.webkit_web_view_get_uri(_webView))) ?? _currentUrl;
        if (updatePendingNavigation)
            _navigationReplayState.TryUpdateReached(_currentUrl);
        UpdateHistorySnapshot(
            LinuxNativeInterop.webkit_web_view_can_go_back(_webView),
            LinuxNativeInterop.webkit_web_view_can_go_forward(_webView));
    }

    [SupportedOSPlatform("linux")]
    private void OnLoadChanged(IntPtr webView, LinuxNativeInterop.WebKitLoadEvent loadEvent, IntPtr userData)
    {
        if (loadEvent is LinuxNativeInterop.WebKitLoadEvent.Started or LinuxNativeInterop.WebKitLoadEvent.Redirected)
            _activeContextMenuTargetToken = null;

        switch (loadEvent)
        {
            case LinuxNativeInterop.WebKitLoadEvent.Started:
                var navigationId = _runtimeNavigationLifecycle.StartNavigation();
                _navigationReplayState.TrackNavigationStarted(
                    navigationId,
                    TryCreateUri(LinuxNativeInterop.ConvertUtf8Pointer(LinuxNativeInterop.webkit_web_view_get_uri(webView))),
                    isRedirected: false);
                break;

            case LinuxNativeInterop.WebKitLoadEvent.Redirected:
                _navigationReplayState.TrackNavigationStarted(
                    _runtimeNavigationLifecycle.CurrentNavigationId,
                    TryCreateUri(LinuxNativeInterop.ConvertUtf8Pointer(LinuxNativeInterop.webkit_web_view_get_uri(webView))),
                    isRedirected: true);
                NavigationStarted?.Invoke(
                    this,
                    new NativeWebViewNavigationStartedEventArgs(
                        TryCreateUri(LinuxNativeInterop.ConvertUtf8Pointer(LinuxNativeInterop.webkit_web_view_get_uri(webView))),
                        isRedirected: true));
                break;

            case LinuxNativeInterop.WebKitLoadEvent.Committed:
                SyncNavigationSnapshotFromRuntimeOnGtkThread(updatePendingNavigation: false);
                break;

            case LinuxNativeInterop.WebKitLoadEvent.Finished:
                SyncNavigationSnapshotFromRuntimeOnGtkThread(updatePendingNavigation: false);
                if (!_runtimeNavigationLifecycle.TryFinishNavigation(out var finishedNavigationId))
                    break;

                _navigationReplayState.CompleteNavigation(finishedNavigationId, _currentUrl);
                var faviconRefreshVersion = Interlocked.Increment(ref _faviconRefreshVersion);
                _ = RefreshRuntimeFaviconAsync(faviconRefreshVersion);
                NavigationCompleted?.Invoke(
                    this,
                    new NativeWebViewNavigationCompletedEventArgs(_currentUrl, isSuccess: true, httpStatusCode: 200));
                break;
        }
    }

    private async Task RefreshRuntimeFaviconAsync(int refreshVersion)
    {
        try
        {
            var previousUri = _faviconUri;
            var faviconUri = await NativeWebViewFaviconSupport.ResolveDeclaredFaviconUriAsync(
                ExecuteScriptAsync,
                _currentUrl,
                CancellationToken.None).ConfigureAwait(false);
            if (_disposed || refreshVersion != Volatile.Read(ref _faviconRefreshVersion))
            {
                return;
            }

            if (AreSameUri(previousUri, faviconUri))
            {
                return;
            }

            _faviconUri = faviconUri;
            FaviconChanged?.Invoke(this, new NativeWebViewFaviconChangedEventArgs(faviconUri));
        }
        catch
        {
            // Favicon discovery is best-effort and must not affect navigation.
        }
    }

    private async Task<Uri?> ResolveRuntimeFaviconUriAsync(CancellationToken cancellationToken)
    {
        var faviconUri = await NativeWebViewFaviconSupport.ResolveDeclaredFaviconUriAsync(
            ExecuteScriptAsync,
            _currentUrl,
            cancellationToken).ConfigureAwait(false);
        _faviconUri = faviconUri;
        return faviconUri;
    }

    private int OnLoadFailed(IntPtr webView, LinuxNativeInterop.WebKitLoadEvent loadEvent, IntPtr failingUri, IntPtr error, IntPtr userData)
    {
        var uri = TryCreateUri(LinuxNativeInterop.ConvertUtf8Pointer(failingUri));
        var message = LinuxNativeInterop.GetBorrowedErrorMessage(error);
        _currentUrl = uri ?? _currentUrl;
        var failedNavigationId = _runtimeNavigationLifecycle.FailNavigation();
        _navigationReplayState.CompleteNavigation(uri, failedNavigationId, _currentUrl);
        UpdateHistorySnapshot(
            LinuxNativeInterop.webkit_web_view_can_go_back(webView),
            LinuxNativeInterop.webkit_web_view_can_go_forward(webView));

        NavigationCompleted?.Invoke(
            this,
            new NativeWebViewNavigationCompletedEventArgs(uri, isSuccess: false, error: message));

        return 0;
    }

    [SupportedOSPlatform("linux")]
    private void OnMouseTargetChanged(IntPtr webView, IntPtr hitTestResult, uint modifiers, IntPtr userData)
    {
        try
        {
            _ = webView;
            _ = modifiers;
            _ = userData;
            if (!CanAcceptMouseStatus(_disposed, Volatile.Read(ref _isRuntimeInitialized)))
            {
                SetStatusText(null);
                return;
            }

            var statusText = hitTestResult != IntPtr.Zero && LinuxNativeInterop.webkit_hit_test_result_context_is_link(hitTestResult)
                ? LinuxNativeInterop.ConvertUtf8Pointer(
                    LinuxNativeInterop.webkit_hit_test_result_get_link_uri(hitTestResult),
                    NativeWebViewStatusTextNormalizer.MaximumLength * 4)
                : null;
            SetStatusText(statusText);
        }
        catch
        {
            try
            {
                SetStatusText(null);
            }
            catch
            {
                // Managed exceptions must never cross the native GTK callback boundary.
            }
        }
    }

    internal static bool CanAcceptMouseStatus(bool isDisposed, bool isRuntimeInitialized) =>
        !isDisposed && isRuntimeInitialized;

    [SupportedOSPlatform("linux")]
    private void OnZoomLevelChanged(IntPtr instance, IntPtr parameterSpec, IntPtr userData)
    {
        _ = parameterSpec;
        _ = userData;
        try
        {
            if (_disposed || !Volatile.Read(ref _isRuntimeInitialized) || instance == IntPtr.Zero)
                return;

            UpdateZoomFactor(LinuxNativeInterop.webkit_web_view_get_zoom_level(instance));
        }
        catch
        {
            // Managed exceptions must never cross the native GTK callback boundary.
        }
    }

    private readonly record struct PendingRuntimeNavigation(
        Uri? Uri,
        int Version,
        bool IsRuntimeReady);

    private void SetStatusText(string? statusText)
    {
        var normalized = NativeWebViewStatusTextNormalizer.Normalize(statusText);
        if (string.Equals(_statusText, normalized, StringComparison.Ordinal))
            return;

        _statusText = normalized;
        StatusTextChanged?.Invoke(this, new NativeWebViewStatusTextChangedEventArgs(normalized));
    }

    private void UpdateZoomFactor(double zoomFactor)
    {
        if (_disposed || !NativeWebViewZoomFactor.HasChanged(_zoomFactor, zoomFactor))
            return;

        _zoomFactor = zoomFactor;
        ZoomFactorChanged?.Invoke(this, new NativeWebViewZoomFactorChangedEventArgs(zoomFactor));
    }

    private void OnDownloadStarted(IntPtr context, IntPtr download, IntPtr userData)
    {
        _ = context;
        _ = userData;

        if (download == IntPtr.Zero)
        {
            return;
        }

        LinuxNativeInterop.g_object_ref(download);

        var uri = TryCreateUri(LinuxNativeInterop.ConvertUtf8Pointer(LinuxNativeInterop.webkit_download_get_uri(download)))
            ?? _currentUrl
            ?? new Uri("about:blank", UriKind.Relative);

        lock (_downloadUris)
        {
            _downloadUris[download] = uri;
        }

        _signalSubscriptions.Add(LinuxNativeInterop.ConnectSignal(
            download,
            "decide-destination",
            new LinuxNativeInterop.DownloadDecideDestinationSignal(OnDownloadDecideDestination)));
        _signalSubscriptions.Add(LinuxNativeInterop.ConnectSignal(
            download,
            "received-data",
            new LinuxNativeInterop.DownloadReceivedDataSignal(OnDownloadReceivedData)));
        _signalSubscriptions.Add(LinuxNativeInterop.ConnectSignal(
            download,
            "failed",
            new LinuxNativeInterop.DownloadFailedSignal(OnDownloadFailed)));
        _signalSubscriptions.Add(LinuxNativeInterop.ConnectSignal(
            download,
            "finished",
            new LinuxNativeInterop.DownloadFinishedSignal(OnDownloadFinished)));
    }

    private int OnDownloadDecideDestination(IntPtr download, IntPtr suggestedFilename, IntPtr userData)
    {
        _ = userData;

        var uri = GetDownloadUri(download) ?? new Uri("about:blank", UriKind.Relative);
        NativeWebViewDownloadManager.NativeWebViewDownloadItem? item = null;
        PendingProgrammaticDownload? pendingRequest = null;
        var options = new NativeWebViewDownloadRequestOptions
        {
            SuggestedFileName = LinuxNativeInterop.ConvertUtf8Pointer(suggestedFilename),
        };

        try
        {
            pendingRequest = TakePendingProgrammaticDownload(uri);
            options = MergeDownloadOptions(pendingRequest?.Options, options);
            var args = _downloadManager
                .PrepareDownloadAsync(uri, options, new NativeWebViewDownloadNativeOperation
                {
                    CancelAsync = cancellationToken =>
                    {
                        cancellationToken.ThrowIfCancellationRequested();
                        LinuxNativeInterop.webkit_download_cancel(download);
                        item?.MarkCanceled("Download was canceled.");
                        return Task.FromResult(NativeWebViewDownloadActionResult.Success());
                    },
                })
                .GetAwaiter()
                .GetResult();
            item = (NativeWebViewDownloadManager.NativeWebViewDownloadItem)args.Item;
            pendingRequest?.TrySetResult(item);

            if (args.Cancel || string.IsNullOrWhiteSpace(args.DestinationPath))
            {
                LinuxNativeInterop.webkit_download_cancel(download);
                item.MarkCanceled("Download was canceled before a destination was selected.");
                return 1;
            }

            item.SetDestination(args.DestinationPath, args.AllowOverwrite);
            var destinationUri = new Uri(Path.GetFullPath(args.DestinationPath)).AbsoluteUri;
            LinuxNativeInterop.webkit_download_set_allow_overwrite(download, args.AllowOverwrite);
            LinuxNativeInterop.webkit_download_set_destination(download, destinationUri);
            item.MarkStarted();
            lock (_downloadItems)
            {
                _downloadItems[download] = item;
            }

            return 1;
        }
        catch (Exception ex)
        {
            LinuxNativeInterop.webkit_download_cancel(download);
            item?.MarkFailed(ex.Message, ex.GetType().Name);
            pendingRequest?.TrySetException(ex);
            return 1;
        }
    }

    private void OnDownloadReceivedData(IntPtr download, ulong dataLength, IntPtr userData)
    {
        _ = dataLength;
        _ = userData;

        if (TryGetDownloadItem(download, out var item))
        {
            item.UpdateProgress(
                checked((long)Math.Min((ulong)long.MaxValue, LinuxNativeInterop.webkit_download_get_received_data_length(download))),
                totalBytesToReceive: null,
                progress: LinuxNativeInterop.webkit_download_get_estimated_progress(download));
        }
    }

    private void OnDownloadFailed(IntPtr download, IntPtr error, IntPtr userData)
    {
        _ = userData;

        if (TryGetDownloadItem(download, out var item))
        {
            var message = LinuxNativeInterop.GetBorrowedErrorMessage(error);
            if (item.Snapshot.State != NativeWebViewDownloadState.Canceled)
            {
                item.MarkFailed(message, "WebKitDownloadFailed");
            }
        }

        RemoveDownloadItem(download);
    }

    private void OnDownloadFinished(IntPtr download, IntPtr userData)
    {
        _ = userData;

        if (TryGetDownloadItem(download, out var item))
        {
            item.UpdateProgress(
                checked((long)Math.Min((ulong)long.MaxValue, LinuxNativeInterop.webkit_download_get_received_data_length(download))),
                totalBytesToReceive: null,
                progress: 1);
            item.MarkCompleted();
        }

        RemoveDownloadItem(download);
    }

    private bool TryGetDownloadItem(
        IntPtr download,
        out NativeWebViewDownloadManager.NativeWebViewDownloadItem item)
    {
        lock (_downloadItems)
        {
            return _downloadItems.TryGetValue(download, out item!);
        }
    }

    private void RemoveDownloadItem(IntPtr download)
    {
        lock (_downloadItems)
        {
            _downloadItems.Remove(download);
        }

        lock (_downloadUris)
        {
            _downloadUris.Remove(download);
        }

        LinuxNativeInterop.g_object_unref(download);
    }

    private Uri? GetDownloadUri(IntPtr download)
    {
        lock (_downloadUris)
        {
            return _downloadUris.TryGetValue(download, out var uri) ? uri : null;
        }
    }

    private int OnDecidePolicy(IntPtr webView, IntPtr decision, LinuxNativeInterop.WebKitPolicyDecisionType decisionType, IntPtr userData)
    {
        var request = decisionType switch
        {
            LinuxNativeInterop.WebKitPolicyDecisionType.NavigationAction => LinuxNativeInterop.webkit_navigation_policy_decision_get_request(decision),
            LinuxNativeInterop.WebKitPolicyDecisionType.NewWindowAction => LinuxNativeInterop.webkit_navigation_policy_decision_get_request(decision),
            LinuxNativeInterop.WebKitPolicyDecisionType.Response => LinuxNativeInterop.webkit_response_policy_decision_get_request(decision),
            _ => IntPtr.Zero,
        };

        var uri = request == IntPtr.Zero
            ? null
            : TryCreateUri(LinuxNativeInterop.ConvertUtf8Pointer(LinuxNativeInterop.webkit_uri_request_get_uri(request)));

        switch (decisionType)
        {
            case LinuxNativeInterop.WebKitPolicyDecisionType.NavigationAction:
                {
                    var args = new NativeWebViewNavigationStartedEventArgs(uri, isRedirected: false);
                    NavigationStarted?.Invoke(this, args);
                    if (args.Cancel)
                    {
                        LinuxNativeInterop.webkit_policy_decision_ignore(decision);
                        return 1;
                    }

                    break;
                }

            case LinuxNativeInterop.WebKitPolicyDecisionType.NewWindowAction:
                {
                    var args = new NativeWebViewNewWindowRequestedEventArgs(uri);
                    NewWindowRequested?.Invoke(this, args);
                    if (args.Handled)
                    {
                        LinuxNativeInterop.webkit_policy_decision_ignore(decision);
                        return 1;
                    }

                    break;
                }

            case LinuxNativeInterop.WebKitPolicyDecisionType.Response:
                {
                    var method = request == IntPtr.Zero
                        ? "GET"
                        : LinuxNativeInterop.ConvertUtf8Pointer(LinuxNativeInterop.webkit_uri_request_get_http_method(request)) ?? "GET";

                    var args = new NativeWebViewResourceRequestedEventArgs(uri, method);
                    WebResourceRequested?.Invoke(this, args);
                    if (args.Handled)
                    {
                        LinuxNativeInterop.webkit_policy_decision_ignore(decision);
                        return 1;
                    }

                    break;
                }
        }

        return 0;
    }

    private void OnScriptMessageReceived(IntPtr manager, IntPtr jsResult, IntPtr userData)
    {
        var json = LinuxNativeInterop.ConvertJavaScriptResultToJson(jsResult);
        string? message = null;

        if (!string.IsNullOrWhiteSpace(json))
        {
            try
            {
                using var document = JsonDocument.Parse(json);
                if (document.RootElement.ValueKind == JsonValueKind.String)
                {
                    message = document.RootElement.GetString();
                }
            }
            catch
            {
                // Keep JSON only when payload is not parseable as a JSON string.
            }
        }

        WebMessageReceived?.Invoke(this, new NativeWebViewMessageReceivedEventArgs(message, json));
    }

    private int OnContextMenu(IntPtr webView, IntPtr contextMenu, IntPtr eventHandle, IntPtr hitTestResult, IntPtr userData)
    {
        if (!_isContextMenuEnabled)
        {
            return 1;
        }

        ClearContextMenuActions();
        NativeWebViewContextMenuTarget? target = null;
        if (hitTestResult != IntPtr.Zero && LinuxNativeInterop.webkit_hit_test_result_context_is_editable(hitTestResult))
        {
            var token = Guid.NewGuid().ToString("N");
            _activeContextMenuTargetToken = token;
            target = new NativeWebViewContextMenuTarget(token, true, _currentUrl, frameUri: null, isMainFrame: false);
        }
        else
        {
            _activeContextMenuTargetToken = null;
        }

        var args = new NativeWebViewContextMenuRequestedEventArgs(0, 0, target);
        ContextMenuRequested?.Invoke(this, args);
        if (!args.Handled && target is not null)
        {
            foreach (var descriptor in args.AdditionalItems)
                AppendContextMenuItem(contextMenu, descriptor, target);
        }
        return args.Handled ? 1 : 0;
    }

    private void AppendContextMenuItem(
        IntPtr menu,
        NativeWebViewContextMenuItem descriptor,
        NativeWebViewContextMenuTarget target)
    {
        IntPtr item;
        switch (descriptor.Kind)
        {
            case NativeWebViewContextMenuItemKind.Separator:
                item = LinuxNativeInterop.webkit_context_menu_item_new_separator();
                break;
            case NativeWebViewContextMenuItemKind.Submenu:
                var submenu = LinuxNativeInterop.webkit_context_menu_new();
                foreach (var child in descriptor.Children)
                    AppendContextMenuItem(submenu, child, target);
                item = LinuxNativeInterop.webkit_context_menu_item_new_with_submenu(descriptor.Label, submenu);
                LinuxNativeInterop.g_object_unref(submenu);
                break;
            case NativeWebViewContextMenuItemKind.Command:
                var action = LinuxNativeInterop.g_simple_action_new($"nativewebview-{Guid.NewGuid():N}", IntPtr.Zero);
                LinuxNativeInterop.g_simple_action_set_enabled(action, descriptor.IsEnabled);
                _contextMenuActions[action] = (descriptor.Id, target);
                _contextMenuActionSubscriptions.Add(LinuxNativeInterop.ConnectSignal(
                    action,
                    "activate",
                    new LinuxNativeInterop.ActionActivateSignal(OnContextMenuActionActivated)));
                item = LinuxNativeInterop.webkit_context_menu_item_new_from_gaction(action, descriptor.Label, IntPtr.Zero);
                LinuxNativeInterop.g_object_unref(action);
                break;
            default:
                throw new ArgumentOutOfRangeException(nameof(descriptor));
        }

        if (item == IntPtr.Zero)
            return;
        LinuxNativeInterop.webkit_context_menu_append(menu, item);
        LinuxNativeInterop.g_object_unref(item);
    }

    private void OnContextMenuActionActivated(IntPtr action, IntPtr parameter, IntPtr userData)
    {
        if (_contextMenuActions.TryGetValue(action, out var invocation))
        {
            ContextMenuCommandInvoked?.Invoke(
                this,
                new NativeWebViewContextMenuCommandInvokedEventArgs(invocation.CommandId, invocation.Target));
        }
    }

    private void ClearContextMenuActions()
    {
        DisposeSubscriptions(_contextMenuActionSubscriptions);
        _contextMenuActionSubscriptions.Clear();
        _contextMenuActions.Clear();
    }

    internal static void DisposeSubscriptions(IReadOnlyList<IDisposable> subscriptions)
    {
        for (var index = 0; index < subscriptions.Count; index++)
        {
            try
            {
                subscriptions[index].Dispose();
            }
            catch
            {
                // Native teardown is best effort; continue releasing every remaining resource.
            }
        }
    }

    public async Task<bool> InsertTextAtContextMenuTargetAsync(
        NativeWebViewContextMenuTarget target,
        string text,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(target);
        ArgumentNullException.ThrowIfNull(text);
        EnsureNotDisposed();
        if (!target.IsEditable || !string.Equals(target.Token, _activeContextMenuTargetToken, StringComparison.Ordinal))
            return false;

        _activeContextMenuTargetToken = null;
        if (!OperatingSystem.IsLinux() || _webView == IntPtr.Zero)
            return false;

        await LinuxGtkDispatcher.InvokeAsync(
            () => LinuxNativeInterop.webkit_web_view_execute_editing_command_with_argument(_webView, "InsertText", text),
            cancellationToken).ConfigureAwait(false);
        return true;
    }

    private void OnCloseRequested(IntPtr webView, IntPtr userData)
    {
        DestroyRequested?.Invoke(this, new NativeWebViewDestroyRequestedEventArgs("WindowCloseRequested"));
    }

    private static string BuildDispatchScript(string payloadExpression)
    {
        return $"(function() {{ var payload = {payloadExpression}; if (window.chrome && window.chrome.webview && typeof window.chrome.webview.__dispatchMessage === 'function') {{ window.chrome.webview.__dispatchMessage(payload); }} else {{ window.dispatchEvent(new MessageEvent(\"message\", {{ data: payload }})); }} return null; }})();";
    }

    private static string ToNavigationString(Uri uri)
    {
        return uri.IsAbsoluteUri
            ? uri.AbsoluteUri
            : uri.ToString();
    }

    private static IReadOnlyList<string> ParsePreferredLanguages(string? language)
    {
        if (string.IsNullOrWhiteSpace(language))
        {
            return Array.Empty<string>();
        }

        var values = language.Split([',', ';', '\r', '\n', '\t'], StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
        return values.Length == 0
            ? Array.Empty<string>()
            : values;
    }

    private static string ResolveCookieStoragePath(string cookieDataFolder)
    {
        var fullPath = Path.GetFullPath(cookieDataFolder);

        if (Path.HasExtension(fullPath))
        {
            return fullPath;
        }

        return Path.Combine(fullPath, "cookies.sqlite");
    }

    internal sealed record LinuxPersistentStorageConfiguration(
        string? BaseDataDirectory,
        string? BaseCacheDirectory);

    private static Uri? TryCreateUri(string? uri)
    {
        return Uri.TryCreate(uri, UriKind.RelativeOrAbsolute, out var parsed)
            ? parsed
            : null;
    }

    private static bool AreSameUri(Uri? left, Uri? right)
    {
        if (left is null || right is null)
        {
            return left is null && right is null;
        }

        var leftValue = left.IsAbsoluteUri ? left.AbsoluteUri : left.ToString();
        var rightValue = right.IsAbsoluteUri ? right.AbsoluteUri : right.ToString();
        return string.Equals(leftValue, rightValue, StringComparison.OrdinalIgnoreCase);
    }

    private static LinuxHostWindowHandle CreateHostWindowOnGtkThread()
    {
        var gtkWindow = LinuxNativeInterop.gtk_window_new(LinuxNativeInterop.GtkWindowType.Popup);
        if (gtkWindow == IntPtr.Zero)
        {
            throw new InvalidOperationException("Unable to create the GTK host window.");
        }

        LinuxNativeInterop.gtk_window_set_decorated(gtkWindow, false);
        LinuxNativeInterop.gtk_window_set_resizable(gtkWindow, true);
        LinuxNativeInterop.gtk_widget_realize(gtkWindow);
        LinuxNativeInterop.gtk_widget_show_all(gtkWindow);

        var gdkWindow = LinuxNativeInterop.gtk_widget_get_window(gtkWindow);
        if (gdkWindow == IntPtr.Zero)
        {
            LinuxNativeInterop.gtk_widget_destroy(gtkWindow);
            throw new InvalidOperationException("GTK did not expose a realized GDK window for the Linux host.");
        }

        // This window is embedded beneath an Avalonia X11 host. It must not wait
        // for frame acknowledgements from a window manager that does not manage it.
        LinuxNativeInterop.gdk_x11_window_set_frame_sync_enabled(gdkWindow, false);

        var xid = LinuxNativeInterop.gdk_x11_window_get_xid(gdkWindow);
        if (xid == IntPtr.Zero)
        {
            LinuxNativeInterop.gtk_widget_destroy(gtkWindow);
            throw new InvalidOperationException("GTK did not expose an X11 child window for the Linux host.");
        }

        return new LinuxHostWindowHandle(gtkWindow, xid);
    }

    private static LinuxHostWindowHandle ResolveExistingGtkWindowOnGtkThread(nint gtkWindow)
    {
        if (gtkWindow == IntPtr.Zero)
        {
            throw new InvalidOperationException("GTK window handle is invalid.");
        }

        LinuxNativeInterop.gtk_widget_realize(gtkWindow);

        var gdkWindow = LinuxNativeInterop.gtk_widget_get_window(gtkWindow);
        if (gdkWindow == IntPtr.Zero)
        {
            throw new InvalidOperationException("GTK did not expose a realized GDK window for the Linux host.");
        }

        var xid = LinuxNativeInterop.gdk_x11_window_get_xid(gdkWindow);
        if (xid == IntPtr.Zero)
        {
            throw new InvalidOperationException("GTK did not expose an X11 window for the Linux host.");
        }

        return new LinuxHostWindowHandle(gtkWindow, xid);
    }

    private async Task<INativeWebViewDownloadItem> StartDownloadAsyncCore(
        Uri uri,
        NativeWebViewDownloadRequestOptions? options,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(uri);
        cancellationToken.ThrowIfCancellationRequested();
        if (!OperatingSystem.IsLinux())
        {
            throw new PlatformNotSupportedException("Programmatic downloads are only supported by this backend on Linux.");
        }

        await EnsureRuntimeInitializedAsync(cancellationToken).ConfigureAwait(false);
        cancellationToken.ThrowIfCancellationRequested();

        await _programmaticDownloadGate.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            var pending = new PendingProgrammaticDownload(uri, options);
            using var registration = cancellationToken.Register(static state =>
                ((PendingProgrammaticDownload)state!).TrySetCanceled(), pending);

            lock (_pendingDownloadGate)
            {
                _pendingProgrammaticDownloads.Add(pending);
            }

            Navigate(uri);

            try
            {
                return await pending.Task.ConfigureAwait(false);
            }
            finally
            {
                RemovePendingProgrammaticDownload(pending);
            }
        }
        finally
        {
            _programmaticDownloadGate.Release();
        }
    }

    private PendingProgrammaticDownload? TakePendingProgrammaticDownload(Uri uri)
    {
        lock (_pendingDownloadGate)
        {
            for (var i = 0; i < _pendingProgrammaticDownloads.Count; i++)
            {
                var pending = _pendingProgrammaticDownloads[i];
                if (!UriEquals(pending.Uri, uri))
                {
                    continue;
                }

                _pendingProgrammaticDownloads.RemoveAt(i);
                return pending;
            }

            if (_pendingProgrammaticDownloads.Count == 1)
            {
                var pending = _pendingProgrammaticDownloads[0];
                _pendingProgrammaticDownloads.RemoveAt(0);
                return pending;
            }
        }

        return null;
    }

    private void RemovePendingProgrammaticDownload(PendingProgrammaticDownload pending)
    {
        lock (_pendingDownloadGate)
        {
            _pendingProgrammaticDownloads.Remove(pending);
        }
    }

    private static NativeWebViewDownloadRequestOptions MergeDownloadOptions(
        NativeWebViewDownloadRequestOptions? preferred,
        NativeWebViewDownloadRequestOptions fallback)
    {
        if (preferred is null)
        {
            return fallback;
        }

        return new NativeWebViewDownloadRequestOptions
        {
            SuggestedFileName = preferred.SuggestedFileName ?? fallback.SuggestedFileName,
            DestinationPath = preferred.DestinationPath ?? fallback.DestinationPath,
            AllowOverwrite = preferred.AllowOverwrite || fallback.AllowOverwrite,
            MimeType = preferred.MimeType ?? fallback.MimeType,
            ContentDisposition = preferred.ContentDisposition ?? fallback.ContentDisposition,
            TotalBytesToReceive = preferred.TotalBytesToReceive ?? fallback.TotalBytesToReceive,
        };
    }

    private static bool UriEquals(Uri left, Uri right) =>
        string.Equals(NormalizeUri(left), NormalizeUri(right), StringComparison.OrdinalIgnoreCase);

    private static string NormalizeUri(Uri uri) =>
        uri.IsAbsoluteUri ? uri.AbsoluteUri : uri.ToString();

    private void EnsureFeature(NativeWebViewFeature feature, string operation)
    {
        if (!Features.Supports(feature))
        {
            throw new NotSupportedException($"{operation} is not supported on platform '{Platform}'.");
        }
    }

    private void EnsureNotDisposed()
    {
        ObjectDisposedException.ThrowIf(_disposed, this);
    }

    private readonly record struct LinuxHostWindowHandle(nint GtkWindow, nint Xid);

    private sealed class PendingProgrammaticDownload
    {
        private readonly TaskCompletionSource<INativeWebViewDownloadItem> _completion =
            new(TaskCreationOptions.RunContinuationsAsynchronously);

        public PendingProgrammaticDownload(Uri uri, NativeWebViewDownloadRequestOptions? options)
        {
            Uri = uri;
            Options = options;
        }

        public Uri Uri { get; }

        public NativeWebViewDownloadRequestOptions? Options { get; }

        public Task<INativeWebViewDownloadItem> Task => _completion.Task;

        public void TrySetResult(INativeWebViewDownloadItem item) =>
            _completion.TrySetResult(item);

        public void TrySetException(Exception exception) =>
            _completion.TrySetException(exception);

        public void TrySetCanceled() =>
            _completion.TrySetCanceled();
    }
}
