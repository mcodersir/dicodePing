using System.Runtime.InteropServices;
using System.Text.Json;

namespace NativeWebView.Platform.Linux;

internal static class LinuxGtkDispatcher
{
    private static readonly Lock Gate = new();
    private static Task<bool>? _startTask;
    private static int _gtkThreadId;

    public static async Task EnsureStartedAsync(CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();

        if (!OperatingSystem.IsLinux())
        {
            throw new PlatformNotSupportedException("GTK initialization is only supported on Linux.");
        }

        Task<bool> startTask;
        lock (Gate)
        {
            startTask = _startTask ??= StartAsync();
        }

        if (!await startTask.ConfigureAwait(false))
        {
            throw new InvalidOperationException("Unable to initialize GTK3 on Linux.");
        }
    }

    public static async Task InvokeAsync(Action action, CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(action);
        await InvokeAsync(
            () =>
            {
                action();
                return true;
            },
            cancellationToken).ConfigureAwait(false);
    }

    public static async Task<T> InvokeAsync<T>(Func<T> action, CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(action);
        cancellationToken.ThrowIfCancellationRequested();
        await EnsureStartedAsync(cancellationToken).ConfigureAwait(false);

        if (Environment.CurrentManagedThreadId == _gtkThreadId)
        {
            cancellationToken.ThrowIfCancellationRequested();
            return action();
        }

        var completion = new TaskCompletionSource<T>(TaskCreationOptions.RunContinuationsAsynchronously);
        var cancellationState = new LinuxCancellationState<T>(completion, cancellationToken);
        using var registration = cancellationToken.Register(
            static state => ((LinuxCancellationState<T>)state!).Cancel(),
            cancellationState);

        LinuxNativeInterop.EnqueueOnGtkThread(() =>
        {
            if (!cancellationState.TryBeginExecution())
                return;

            try
            {
                completion.TrySetResult(action());
            }
            catch (Exception ex)
            {
                completion.TrySetException(ex);
            }
        });

        return await completion.Task.ConfigureAwait(false);
    }

    private static Task<bool> StartAsync()
    {
        var completion = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);

        var thread = new Thread(() =>
        {
            _gtkThreadId = Environment.CurrentManagedThreadId;

            try
            {
                if (!LinuxNativeInterop.InitializeGtk())
                {
                    completion.TrySetResult(false);
                    return;
                }

                completion.TrySetResult(true);
                LinuxNativeInterop.RunGtkLoop();
            }
            catch (Exception ex)
            {
                completion.TrySetException(ex);
            }
        })
        {
            Name = "NativeWebView.GTK",
            IsBackground = true,
        };

        thread.Start();
        return completion.Task;
    }
}

internal sealed class LinuxCancellationState<T>(
    TaskCompletionSource<T> completion,
    CancellationToken cancellationToken)
{
    private int _state;

    public bool TryBeginExecution() =>
        Interlocked.CompareExchange(ref _state, 1, 0) == 0;

    public void Cancel()
    {
        if (Interlocked.CompareExchange(ref _state, 2, 0) == 0)
            completion.TrySetCanceled(cancellationToken);
    }
}

internal sealed class LinuxJavaScriptRequest : IDisposable
{
    private readonly TaskCompletionSource<string?> _completion =
        new(TaskCreationOptions.RunContinuationsAsynchronously);
    private readonly CancellationTokenRegistration _cancellationRegistration;
    private readonly CancellationToken _cancellationToken;
    private readonly Action<IntPtr> _cancelCancellable;
    private readonly Action<IntPtr> _releaseCancellable;
    private GCHandle _managedHandle;
    private int _disposeState;

    public LinuxJavaScriptRequest(CancellationToken cancellationToken)
        : this(
            cancellationToken,
            CreateCancellable(cancellationToken),
            LinuxNativeInterop.CancelCancellable,
            LinuxNativeInterop.ReleaseCancellable)
    {
    }

    internal LinuxJavaScriptRequest(
        CancellationToken cancellationToken,
        IntPtr cancellable,
        Action<IntPtr> cancelCancellable,
        Action<IntPtr> releaseCancellable)
    {
        ArgumentNullException.ThrowIfNull(cancelCancellable);
        ArgumentNullException.ThrowIfNull(releaseCancellable);

        _cancellationToken = cancellationToken;
        Cancellable = cancellable;
        _cancelCancellable = cancelCancellable;
        _releaseCancellable = releaseCancellable;
        try
        {
            if (cancellationToken.CanBeCanceled)
            {
                _cancellationRegistration = cancellationToken.Register(
                    static state => ((LinuxJavaScriptRequest)state!).Cancel(),
                    this);
            }

            _managedHandle = GCHandle.Alloc(this);
        }
        catch
        {
            _cancellationRegistration.Dispose();
            ReleaseCancellable();
            throw;
        }
    }

    public Task<string?> Completion => _completion.Task;

    public IntPtr Cancellable { get; }

    public IntPtr UserData
    {
        get
        {
            ObjectDisposedException.ThrowIf(Volatile.Read(ref _disposeState) != 0, this);
            return GCHandle.ToIntPtr(_managedHandle);
        }
    }

    internal bool IsDisposed => Volatile.Read(ref _disposeState) != 0;

    public void TrySetResult(string? result) => _completion.TrySetResult(result);

    public void TrySetException(Exception exception) => _completion.TrySetException(exception);

    private static IntPtr CreateCancellable(CancellationToken cancellationToken)
    {
        if (!cancellationToken.CanBeCanceled || !OperatingSystem.IsLinux())
            return IntPtr.Zero;

        var cancellable = LinuxNativeInterop.CreateCancellable();
        return cancellable != IntPtr.Zero
            ? cancellable
            : throw new InvalidOperationException("Unable to create a cancellable WebKit operation.");
    }

    private void Cancel()
    {
        try
        {
            if (Cancellable != IntPtr.Zero)
                _cancelCancellable(Cancellable);
        }
        finally
        {
            _completion.TrySetCanceled(_cancellationToken);
        }
    }

    private void ReleaseCancellable()
    {
        if (Cancellable != IntPtr.Zero)
            _releaseCancellable(Cancellable);
    }

    public void Dispose()
    {
        if (Interlocked.Exchange(ref _disposeState, 1) != 0)
            return;

        try
        {
            _cancellationRegistration.Dispose();
            ReleaseCancellable();
        }
        finally
        {
            if (_managedHandle.IsAllocated)
                _managedHandle.Free();
        }
    }
}

internal sealed class LinuxUtf8StringArray : IDisposable
{
    private readonly IntPtr[] _allocatedStrings;

    public LinuxUtf8StringArray(IReadOnlyList<string> values)
    {
        ArgumentNullException.ThrowIfNull(values);

        _allocatedStrings = new IntPtr[values.Count];
        Pointer = Marshal.AllocHGlobal((values.Count + 1) * IntPtr.Size);

        for (var index = 0; index < values.Count; index++)
        {
            _allocatedStrings[index] = Marshal.StringToCoTaskMemUTF8(values[index]);
            Marshal.WriteIntPtr(Pointer, index * IntPtr.Size, _allocatedStrings[index]);
        }

        Marshal.WriteIntPtr(Pointer, values.Count * IntPtr.Size, IntPtr.Zero);
    }

    public IntPtr Pointer { get; }

    public void Dispose()
    {
        foreach (var stringPointer in _allocatedStrings)
        {
            if (stringPointer != IntPtr.Zero)
            {
                Marshal.FreeCoTaskMem(stringPointer);
            }
        }

        if (Pointer != IntPtr.Zero)
        {
            Marshal.FreeHGlobal(Pointer);
        }
    }
}

internal static class LinuxNativeInterop
{
    private const string GtkName = "libgtk-3.so.0";
    private const string GdkName = "libgdk-3.so.0";
    private const string GObjectName = "libgobject-2.0.so.0";
    private const string GlibName = "libglib-2.0.so.0";
    private const string GioName = "libgio-2.0.so.0";
    private const string WebKitName = "libwebkit2gtk-4.1.so.0";
    private const string JavaScriptCoreName = "libjavascriptcoregtk-4.1.so.0";
    private const string X11Name = "libX11.so.6";
    private const string CairoName = "libcairo.so.2";

    private static readonly object GtkInitializationGate = new();
    private static IntPtr _display;

    private static readonly GSourceFunc IdleSourceCallback = static userData =>
    {
        var handle = GCHandle.FromIntPtr(userData);

        try
        {
            ((Action)handle.Target!).Invoke();
        }
        finally
        {
            handle.Free();
        }

        return 0;
    };

    [StructLayout(LayoutKind.Sequential)]
    private struct GError
    {
        public uint Domain;
        public int Code;
        public IntPtr Message;
    }

    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    private delegate int GSourceFunc(IntPtr userData);

    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    private delegate void GDestroyNotify(IntPtr data);

    internal enum GtkWindowType
    {
        TopLevel = 0,
        Popup = 1,
    }

    internal enum WebKitLoadEvent
    {
        Started = 0,
        Redirected = 1,
        Committed = 2,
        Finished = 3,
    }

    internal enum WebKitPolicyDecisionType
    {
        NavigationAction = 0,
        NewWindowAction = 1,
        Response = 2,
    }

    internal enum WebKitNetworkProxyMode
    {
        Default = 0,
        NoProxy = 1,
        Custom = 2,
    }

    internal enum WebKitCookiePersistentStorage
    {
        Text = 0,
        Sqlite = 1,
    }

    internal enum WebKitUserContentInjectedFrames
    {
        AllFrames = 0,
        TopFrame = 1,
    }

    internal enum WebKitUserScriptInjectionTime
    {
        DocumentStart = 0,
        DocumentEnd = 1,
    }

    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    internal delegate void LoadChangedSignal(IntPtr webView, WebKitLoadEvent loadEvent, IntPtr userData);

    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    internal delegate int LoadFailedSignal(IntPtr webView, WebKitLoadEvent loadEvent, IntPtr failingUri, IntPtr error, IntPtr userData);

    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    internal delegate int DecidePolicySignal(IntPtr webView, IntPtr decision, WebKitPolicyDecisionType decisionType, IntPtr userData);

    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    internal delegate void ScriptMessageReceivedSignal(IntPtr manager, IntPtr jsResult, IntPtr userData);

    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    internal delegate int ContextMenuSignal(IntPtr webView, IntPtr contextMenu, IntPtr eventHandle, IntPtr hitTestResult, IntPtr userData);

    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    internal delegate void ActionActivateSignal(IntPtr action, IntPtr parameter, IntPtr userData);

    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    internal delegate void CloseSignal(IntPtr webView, IntPtr userData);

    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    internal delegate int DeleteEventSignal(IntPtr widget, IntPtr eventHandle, IntPtr userData);

    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    internal delegate void DownloadStartedSignal(IntPtr context, IntPtr download, IntPtr userData);

    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    internal delegate int DownloadDecideDestinationSignal(IntPtr download, IntPtr suggestedFilename, IntPtr userData);

    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    internal delegate void DownloadReceivedDataSignal(IntPtr download, ulong dataLength, IntPtr userData);

    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    internal delegate void DownloadFailedSignal(IntPtr download, IntPtr error, IntPtr userData);

    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    internal delegate void DownloadFinishedSignal(IntPtr download, IntPtr userData);

    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    internal delegate void MouseTargetChangedSignal(IntPtr webView, IntPtr hitTestResult, uint modifiers, IntPtr userData);

    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    internal delegate void NotifySignal(IntPtr instance, IntPtr parameterSpec, IntPtr userData);

    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    private delegate void JavaScriptFinishedCallback(IntPtr webView, IntPtr asyncResult, IntPtr userData);

    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    private delegate void SnapshotFinishedCallback(IntPtr webView, IntPtr asyncResult, IntPtr userData);

    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    private delegate int CairoWriteCallback(IntPtr closure, IntPtr data, uint length);

    private static readonly SnapshotFinishedCallback SnapshotFinished = OnSnapshotFinished;
    private static readonly CairoWriteCallback CairoWrite = WriteCairoPngData;

    private sealed class ConnectedSignal : IDisposable
    {
        private readonly IntPtr _instance;
        private GCHandle _delegateHandle;
        private readonly ulong _signalId;
        private bool _disposed;

        public ConnectedSignal(IntPtr instance, GCHandle delegateHandle, ulong signalId)
        {
            _instance = instance;
            _delegateHandle = delegateHandle;
            _signalId = signalId;
            g_object_ref(instance);
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
                g_signal_handler_disconnect(_instance, _signalId);
            }
            finally
            {
                try
                {
                    g_object_unref(_instance);
                }
                finally
                {
                    if (_delegateHandle.IsAllocated)
                        _delegateHandle.Free();
                }
            }
        }
    }

    [DllImport(GtkName)]
    private static extern void gtk_main_iteration();

    [DllImport(GtkName)]
    private static extern bool gtk_init_check(int argc, IntPtr argv);

    [DllImport(GtkName)]
    internal static extern IntPtr gtk_window_new(GtkWindowType type);

    [DllImport(GtkName)]
    internal static extern void gtk_window_set_decorated(IntPtr window, bool setting);

    [DllImport(GtkName)]
    internal static extern void gtk_window_set_resizable(IntPtr window, bool resizable);

    [DllImport(GtkName)]
    internal static extern void gtk_window_resize(IntPtr window, int width, int height);

    [DllImport(GtkName)]
    internal static extern void gtk_window_move(IntPtr window, int x, int y);

    [DllImport(GtkName)]
    internal static extern void gtk_window_present(IntPtr window);

    [DllImport(GtkName)]
    internal static extern void gtk_window_set_title(IntPtr window, [MarshalAs(UnmanagedType.LPUTF8Str)] string title);

    [DllImport(GtkName)]
    internal static extern void gtk_container_add(IntPtr container, IntPtr widget);

    [DllImport(GtkName)]
    internal static extern void gtk_widget_realize(IntPtr widget);

    [DllImport(GtkName)]
    internal static extern void gtk_widget_show_all(IntPtr widget);

    [DllImport(GtkName)]
    internal static extern void gtk_widget_hide(IntPtr widget);

    [DllImport(GtkName)]
    internal static extern void gtk_widget_destroy(IntPtr widget);

    [DllImport(GtkName)]
    internal static extern IntPtr gtk_widget_get_window(IntPtr widget);

    [DllImport(GtkName)]
    internal static extern void gtk_widget_grab_focus(IntPtr widget);

    [DllImport(GdkName)]
    private static extern IntPtr gdk_display_get_default();

    [DllImport(GdkName)]
    private static extern IntPtr gdk_x11_display_get_xdisplay(IntPtr display);

    [DllImport(GdkName)]
    private static extern void gdk_set_allowed_backends([MarshalAs(UnmanagedType.LPUTF8Str)] string backends);

    [DllImport(GdkName)]
    internal static extern IntPtr gdk_x11_window_get_xid(IntPtr window);

    [DllImport(GdkName)]
    internal static extern void gdk_x11_window_set_frame_sync_enabled(IntPtr window, bool frameSyncEnabled);

    [DllImport(X11Name)]
    private static extern int XReparentWindow(
        IntPtr display,
        IntPtr window,
        IntPtr parent,
        int x,
        int y);

    [DllImport(X11Name)]
    private static extern int XMapWindow(IntPtr display, IntPtr window);

    [DllImport(X11Name)]
    private static extern int XFlush(IntPtr display);

    [DllImport(GlibName)]
    private static extern uint g_idle_add_full(int priority, GSourceFunc function, IntPtr data, GDestroyNotify? notify);

    [DllImport(GlibName)]
    private static extern void g_error_free(IntPtr error);

    [DllImport(GlibName)]
    internal static extern void g_free(IntPtr pointer);

    [DllImport(GObjectName)]
    private static extern ulong g_signal_connect_data(
        IntPtr instance,
        [MarshalAs(UnmanagedType.LPUTF8Str)] string detailedSignal,
        IntPtr handler,
        IntPtr data,
        IntPtr destroyData,
        int connectFlags);

    [DllImport(GObjectName)]
    private static extern void g_signal_handler_disconnect(IntPtr instance, ulong handlerId);

    [DllImport(GObjectName)]
    internal static extern void g_object_ref(IntPtr instance);

    [DllImport(GObjectName)]
    internal static extern void g_object_unref(IntPtr instance);

    [DllImport(GioName)]
    private static extern IntPtr g_cancellable_new();

    [DllImport(GioName)]
    private static extern void g_cancellable_cancel(IntPtr cancellable);

    internal static IntPtr CreateCancellable() => g_cancellable_new();

    internal static void CancelCancellable(IntPtr cancellable) => g_cancellable_cancel(cancellable);

    internal static void ReleaseCancellable(IntPtr cancellable) => g_object_unref(cancellable);

    [DllImport(WebKitName)]
    internal static extern IntPtr webkit_web_context_new();

    [DllImport(WebKitName)]
    internal static extern IntPtr webkit_web_context_new_ephemeral();

    [DllImport(WebKitName)]
    internal static extern IntPtr webkit_web_context_new_with_website_data_manager(IntPtr manager);

    [DllImport(WebKitName, EntryPoint = "webkit_website_data_manager_new")]
    internal static extern IntPtr webkit_website_data_manager_new_with_one_directory(
        [MarshalAs(UnmanagedType.LPUTF8Str)] string propertyName,
        [MarshalAs(UnmanagedType.LPUTF8Str)] string propertyValue,
        IntPtr terminator);

    [DllImport(WebKitName, EntryPoint = "webkit_website_data_manager_new")]
    internal static extern IntPtr webkit_website_data_manager_new_with_two_directories(
        [MarshalAs(UnmanagedType.LPUTF8Str)] string firstPropertyName,
        [MarshalAs(UnmanagedType.LPUTF8Str)] string firstPropertyValue,
        [MarshalAs(UnmanagedType.LPUTF8Str)] string secondPropertyName,
        [MarshalAs(UnmanagedType.LPUTF8Str)] string secondPropertyValue,
        IntPtr terminator);

    [DllImport(WebKitName)]
    internal static extern IntPtr webkit_web_context_get_website_data_manager(IntPtr context);

    [DllImport(WebKitName)]
    internal static extern void webkit_web_context_set_preferred_languages(IntPtr context, IntPtr languages);

    [DllImport(WebKitName)]
    internal static extern IntPtr webkit_web_view_new_with_context(IntPtr context);

    [DllImport(WebKitName)]
    internal static extern IntPtr webkit_web_view_get_user_content_manager(IntPtr webView);

    [DllImport(WebKitName)]
    internal static extern IntPtr webkit_web_view_get_settings(IntPtr webView);

    [DllImport(WebKitName)]
    internal static extern IntPtr webkit_web_view_get_uri(IntPtr webView);

    [DllImport(WebKitName)]
    internal static extern void webkit_web_view_load_uri(IntPtr webView, [MarshalAs(UnmanagedType.LPUTF8Str)] string uri);

    [DllImport(WebKitName)]
    internal static extern void webkit_web_view_reload(IntPtr webView);

    [DllImport(WebKitName)]
    internal static extern void webkit_web_view_stop_loading(IntPtr webView);

    [DllImport(WebKitName)]
    internal static extern bool webkit_web_view_can_go_back(IntPtr webView);

    [DllImport(WebKitName)]
    internal static extern bool webkit_web_view_can_go_forward(IntPtr webView);

    [DllImport(WebKitName)]
    internal static extern void webkit_web_view_go_back(IntPtr webView);

    [DllImport(WebKitName)]
    internal static extern void webkit_web_view_go_forward(IntPtr webView);

    [DllImport(WebKitName)]
    internal static extern void webkit_web_view_set_zoom_level(IntPtr webView, double zoomLevel);

    [DllImport(WebKitName)]
    internal static extern double webkit_web_view_get_zoom_level(IntPtr webView);

    [DllImport(WebKitName)]
    internal static extern void webkit_web_view_execute_editing_command_with_argument(
        IntPtr webView,
        [MarshalAs(UnmanagedType.LPUTF8Str)] string command,
        [MarshalAs(UnmanagedType.LPUTF8Str)] string argument);

    [DllImport(WebKitName)]
    internal static extern bool webkit_hit_test_result_context_is_editable(IntPtr hitTestResult);

    [DllImport(WebKitName)]
    internal static extern bool webkit_hit_test_result_context_is_link(IntPtr hitTestResult);

    [DllImport(WebKitName)]
    internal static extern IntPtr webkit_hit_test_result_get_link_uri(IntPtr hitTestResult);

    [DllImport(WebKitName)]
    private static extern void webkit_web_view_get_snapshot(
        IntPtr webView,
        int region,
        int options,
        IntPtr cancellable,
        SnapshotFinishedCallback callback,
        IntPtr userData);

    [DllImport(WebKitName)]
    private static extern IntPtr webkit_web_view_get_snapshot_finish(IntPtr webView, IntPtr asyncResult, out IntPtr error);

    [DllImport(CairoName)]
    private static extern int cairo_surface_write_to_png_stream(
        IntPtr surface,
        CairoWriteCallback writeFunction,
        IntPtr closure);

    [DllImport(CairoName)]
    private static extern void cairo_surface_destroy(IntPtr surface);

    [DllImport(WebKitName)]
    internal static extern IntPtr webkit_context_menu_new();

    [DllImport(WebKitName)]
    internal static extern void webkit_context_menu_append(IntPtr menu, IntPtr item);

    [DllImport(WebKitName)]
    internal static extern IntPtr webkit_context_menu_item_new_separator();

    [DllImport(WebKitName)]
    internal static extern IntPtr webkit_context_menu_item_new_from_gaction(
        IntPtr action,
        [MarshalAs(UnmanagedType.LPUTF8Str)] string label,
        IntPtr target);

    [DllImport(WebKitName)]
    internal static extern IntPtr webkit_context_menu_item_new_with_submenu(
        [MarshalAs(UnmanagedType.LPUTF8Str)] string label,
        IntPtr submenu);

    [DllImport(GioName)]
    internal static extern IntPtr g_simple_action_new(
        [MarshalAs(UnmanagedType.LPUTF8Str)] string name,
        IntPtr parameterType);

    [DllImport(GioName)]
    internal static extern void g_simple_action_set_enabled(IntPtr action, bool enabled);

    [DllImport(WebKitName)]
    private static extern void webkit_web_view_run_javascript(
        IntPtr webView,
        [MarshalAs(UnmanagedType.LPUTF8Str)] string script,
        IntPtr cancellable,
        JavaScriptFinishedCallback callback,
        IntPtr userData);

    [DllImport(WebKitName)]
    private static extern IntPtr webkit_web_view_run_javascript_finish(IntPtr webView, IntPtr asyncResult, out IntPtr error);

    [DllImport(WebKitName)]
    internal static extern IntPtr webkit_web_view_get_inspector(IntPtr webView);

    [DllImport(WebKitName)]
    internal static extern IntPtr webkit_print_operation_new(IntPtr webView);

    [DllImport(WebKitName)]
    internal static extern void webkit_print_operation_print(IntPtr printOperation);

    [DllImport(WebKitName)]
    private static extern IntPtr webkit_javascript_result_get_js_value(IntPtr jsResult);

    [DllImport(WebKitName)]
    private static extern void webkit_javascript_result_unref(IntPtr jsResult);

    [DllImport(WebKitName)]
    internal static extern void webkit_settings_set_enable_developer_extras(IntPtr settings, bool enabled);

    [DllImport(WebKitName)]
    internal static extern void webkit_settings_set_enable_javascript(IntPtr settings, bool enabled);

    [DllImport(WebKitName)]
    internal static extern void webkit_settings_set_user_agent(IntPtr settings, [MarshalAs(UnmanagedType.LPUTF8Str)] string? userAgent);

    [DllImport(WebKitName)]
    internal static extern bool webkit_user_content_manager_register_script_message_handler(
        IntPtr manager,
        [MarshalAs(UnmanagedType.LPUTF8Str)] string name);

    [DllImport(WebKitName)]
    internal static extern void webkit_user_content_manager_add_script(IntPtr manager, IntPtr script);

    [DllImport(WebKitName)]
    internal static extern IntPtr webkit_user_script_new(
        [MarshalAs(UnmanagedType.LPUTF8Str)] string source,
        WebKitUserContentInjectedFrames injectedFrames,
        WebKitUserScriptInjectionTime injectionTime,
        IntPtr allowList,
        IntPtr blockList);

    [DllImport(WebKitName)]
    internal static extern void webkit_user_script_unref(IntPtr userScript);

    [DllImport(WebKitName)]
    internal static extern IntPtr webkit_website_data_manager_get_cookie_manager(IntPtr manager);

    [DllImport(WebKitName)]
    internal static extern void webkit_cookie_manager_set_persistent_storage(
        IntPtr cookieManager,
        [MarshalAs(UnmanagedType.LPUTF8Str)] string filename,
        WebKitCookiePersistentStorage storage);

    [DllImport(WebKitName)]
    internal static extern IntPtr webkit_network_proxy_settings_new(
        [MarshalAs(UnmanagedType.LPUTF8Str)] string defaultProxyUri,
        IntPtr ignoreHosts);

    [DllImport(WebKitName)]
    internal static extern void webkit_network_proxy_settings_free(IntPtr proxySettings);

    [DllImport(WebKitName)]
    internal static extern void webkit_website_data_manager_set_network_proxy_settings(
        IntPtr manager,
        WebKitNetworkProxyMode proxyMode,
        IntPtr proxySettings);

    [DllImport(WebKitName)]
    internal static extern IntPtr webkit_navigation_policy_decision_get_request(IntPtr decision);

    [DllImport(WebKitName)]
    internal static extern IntPtr webkit_response_policy_decision_get_request(IntPtr decision);

    [DllImport(WebKitName)]
    internal static extern void webkit_policy_decision_ignore(IntPtr decision);

    [DllImport(WebKitName)]
    internal static extern void webkit_policy_decision_use(IntPtr decision);

    [DllImport(WebKitName)]
    internal static extern void webkit_policy_decision_download(IntPtr decision);

    [DllImport(WebKitName)]
    internal static extern IntPtr webkit_uri_request_get_uri(IntPtr request);

    [DllImport(WebKitName)]
    internal static extern IntPtr webkit_uri_request_get_http_method(IntPtr request);

    [DllImport(WebKitName)]
    internal static extern IntPtr webkit_download_get_uri(IntPtr download);

    [DllImport(WebKitName)]
    internal static extern void webkit_download_set_destination(
        IntPtr download,
        [MarshalAs(UnmanagedType.LPUTF8Str)] string destinationUri);

    [DllImport(WebKitName)]
    internal static extern void webkit_download_set_allow_overwrite(
        IntPtr download,
        [MarshalAs(UnmanagedType.Bool)] bool allowed);

    [DllImport(WebKitName)]
    internal static extern ulong webkit_download_get_received_data_length(IntPtr download);

    [DllImport(WebKitName)]
    internal static extern double webkit_download_get_estimated_progress(IntPtr download);

    [DllImport(WebKitName)]
    internal static extern void webkit_download_cancel(IntPtr download);

    [DllImport(WebKitName)]
    internal static extern void webkit_web_inspector_show(IntPtr inspector);

    [DllImport(JavaScriptCoreName)]
    private static extern IntPtr jsc_value_to_json(IntPtr value, uint indent);

    [DllImport(JavaScriptCoreName)]
    private static extern IntPtr jsc_value_to_string(IntPtr value);

    public static bool InitializeGtk()
    {
        lock (GtkInitializationGate)
        {
            if (_display != IntPtr.Zero)
            {
                return true;
            }

            try
            {
                var defaultDisplay = gdk_display_get_default();
                if (defaultDisplay != IntPtr.Zero)
                {
                    if (gdk_x11_display_get_xdisplay(defaultDisplay) == IntPtr.Zero)
                    {
                        return false;
                    }

                    _display = defaultDisplay;
                    return true;
                }

                try
                {
                    gdk_set_allowed_backends("x11");
                }
                catch
                {
                    // Best effort. GTK will fail below if X11 is unavailable.
                }

                Environment.SetEnvironmentVariable("WAYLAND_DISPLAY", "/proc/nativewebview-disable-wayland");
                if (!gtk_init_check(0, IntPtr.Zero))
                {
                    return false;
                }

                _display = gdk_display_get_default();
                return _display != IntPtr.Zero && gdk_x11_display_get_xdisplay(_display) != IntPtr.Zero;
            }
            catch
            {
                return false;
            }
        }
    }

    public static void RunGtkLoop()
    {
        while (true)
        {
            gtk_main_iteration();
        }
    }

    public static void EnqueueOnGtkThread(Action action)
    {
        EnqueueOnGtkThread(
            action,
            static callbackHandle => g_idle_add_full(0, IdleSourceCallback, callbackHandle, null));
    }

    internal static void EnqueueOnGtkThread(Action action, Func<IntPtr, uint> registerIdleSource)
    {
        ArgumentNullException.ThrowIfNull(action);
        ArgumentNullException.ThrowIfNull(registerIdleSource);
        var handle = GCHandle.Alloc(action);
        try
        {
            var callbackHandle = GCHandle.ToIntPtr(handle);
            if (registerIdleSource(callbackHandle) == 0)
                throw new InvalidOperationException("Unable to enqueue work on the GTK thread.");
        }
        catch
        {
            if (handle.IsAllocated)
                handle.Free();
            throw;
        }
    }

    public static void AttachX11WindowToParent(IntPtr childWindow, IntPtr parentWindow)
    {
        if (childWindow == IntPtr.Zero)
        {
            throw new InvalidOperationException("Child X11 window handle is invalid.");
        }

        if (parentWindow == IntPtr.Zero)
        {
            throw new InvalidOperationException("Parent X11 window handle is invalid.");
        }

        if (_display == IntPtr.Zero)
        {
            throw new InvalidOperationException("GTK display is not initialized.");
        }

        var xDisplay = gdk_x11_display_get_xdisplay(_display);
        if (xDisplay == IntPtr.Zero)
        {
            throw new InvalidOperationException("Unable to resolve the X11 display for Linux native attachment.");
        }

        // XReparentWindow reports protocol errors asynchronously; its immediate int return is not a
        // Win32-style success code and must not be treated as a failure signal.
        _ = XReparentWindow(xDisplay, childWindow, parentWindow, 0, 0);
        _ = XMapWindow(xDisplay, childWindow);
        _ = XFlush(xDisplay);
    }

    public static IDisposable ConnectSignal<T>(IntPtr instance, string signalName, T handler)
        where T : Delegate
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(signalName);
        ArgumentNullException.ThrowIfNull(handler);

        var delegateHandle = GCHandle.Alloc(handler);
        ulong signalId = 0;
        try
        {
            var functionPointer = Marshal.GetFunctionPointerForDelegate(handler);
            signalId = g_signal_connect_data(instance, signalName, functionPointer, IntPtr.Zero, IntPtr.Zero, 0);

            if (signalId == 0)
                throw new InvalidOperationException($"Unable to connect GTK signal '{signalName}'.");

            return new ConnectedSignal(instance, delegateHandle, signalId);
        }
        catch
        {
            if (signalId != 0)
            {
                try
                {
                    g_signal_handler_disconnect(instance, signalId);
                }
                catch
                {
                    // Preserve the original signal-registration failure.
                }
            }

            if (delegateHandle.IsAllocated)
                delegateHandle.Free();
            throw;
        }
    }

    public static Task<byte[]?> CaptureSnapshotPngAsync(IntPtr webView, CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        if (webView == IntPtr.Zero)
            return Task.FromResult<byte[]?>(null);

        var state = new SnapshotCaptureState(cancellationToken);
        var handle = GCHandle.Alloc(state);
        state.SetHandle(handle);
        try
        {
            webkit_web_view_get_snapshot(
                webView,
                region: 0,
                options: 0,
                state.Cancellable,
                SnapshotFinished,
                GCHandle.ToIntPtr(handle));
            return state.Task;
        }
        catch
        {
            state.Dispose();
            throw;
        }
    }

    private static void OnSnapshotFinished(IntPtr webView, IntPtr asyncResult, IntPtr userData)
    {
        var handle = GCHandle.FromIntPtr(userData);
        var state = (SnapshotCaptureState)handle.Target!;
        IntPtr surface = IntPtr.Zero;
        try
        {
            surface = webkit_web_view_get_snapshot_finish(webView, asyncResult, out var error);
            if (error != IntPtr.Zero)
            {
                g_error_free(error);
                state.TrySetResult(null);
                return;
            }

            if (surface == IntPtr.Zero)
            {
                state.TrySetResult(null);
                return;
            }

            using var stream = new MemoryStream();
            var streamHandle = GCHandle.Alloc(stream);
            try
            {
                var status = cairo_surface_write_to_png_stream(surface, CairoWrite, GCHandle.ToIntPtr(streamHandle));
                state.TrySetResult(status == 0 && stream.Length > 0 ? stream.ToArray() : null);
            }
            finally
            {
                streamHandle.Free();
            }
        }
        catch (Exception exception)
        {
            state.TrySetException(exception);
        }
        finally
        {
            if (surface != IntPtr.Zero)
                cairo_surface_destroy(surface);
            state.Dispose();
        }
    }

    private static int WriteCairoPngData(IntPtr closure, IntPtr data, uint length)
    {
        try
        {
            var stream = (MemoryStream)GCHandle.FromIntPtr(closure).Target!;
            var buffer = new byte[checked((int)length)];
            Marshal.Copy(data, buffer, 0, buffer.Length);
            stream.Write(buffer, 0, buffer.Length);
            return 0;
        }
        catch
        {
            return 11;
        }
    }

    private sealed class SnapshotCaptureState : IDisposable
    {
        private readonly TaskCompletionSource<byte[]?> _completion =
            new(TaskCreationOptions.RunContinuationsAsynchronously);
        private readonly CancellationToken _cancellationToken;
        private readonly CancellationTokenRegistration _cancellationRegistration;
        private GCHandle _selfHandle;
        private int _disposed;

        public SnapshotCaptureState(CancellationToken cancellationToken)
        {
            _cancellationToken = cancellationToken;
            Cancellable = g_cancellable_new();
            _cancellationRegistration = cancellationToken.Register(
                static state => ((SnapshotCaptureState)state!).Cancel(),
                this);
        }

        public IntPtr Cancellable { get; }

        public Task<byte[]?> Task => _completion.Task;

        public void SetHandle(GCHandle handle) => _selfHandle = handle;

        public void TrySetResult(byte[]? data) => _completion.TrySetResult(data);

        public void TrySetException(Exception exception) => _completion.TrySetException(exception);

        private void Cancel()
        {
            if (Cancellable != IntPtr.Zero)
                g_cancellable_cancel(Cancellable);
            _completion.TrySetCanceled(_cancellationToken);
        }

        public void Dispose()
        {
            if (Interlocked.Exchange(ref _disposed, 1) != 0)
                return;

            _cancellationRegistration.Dispose();
            if (Cancellable != IntPtr.Zero)
                g_object_unref(Cancellable);
            if (_selfHandle.IsAllocated)
                _selfHandle.Free();
        }
    }

    public static async Task<string?> RunJavaScriptAsync(IntPtr webView, string script, CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(script);
        cancellationToken.ThrowIfCancellationRequested();

        var request = new LinuxJavaScriptRequest(cancellationToken);

        try
        {
            cancellationToken.ThrowIfCancellationRequested();
            webkit_web_view_run_javascript(
                webView,
                script,
                request.Cancellable,
                OnJavaScriptFinished,
                request.UserData);
        }
        catch
        {
            request.Dispose();
            throw;
        }

        return await request.Completion.ConfigureAwait(false);
    }

    public static string? ConvertJavaScriptResultToJson(IntPtr javascriptResult)
    {
        if (javascriptResult == IntPtr.Zero)
        {
            return "null";
        }

        var value = webkit_javascript_result_get_js_value(javascriptResult);
        return ConvertJavaScriptValueToJson(value);
    }

    public static string ConvertJavaScriptValueToJson(IntPtr value)
    {
        if (value == IntPtr.Zero)
        {
            return "null";
        }

        var jsonPointer = jsc_value_to_json(value, 0);
        if (jsonPointer != IntPtr.Zero)
        {
            try
            {
                return Marshal.PtrToStringUTF8(jsonPointer) ?? "null";
            }
            finally
            {
                g_free(jsonPointer);
            }
        }

        var stringPointer = jsc_value_to_string(value);
        if (stringPointer != IntPtr.Zero)
        {
            try
            {
                var stringValue = Marshal.PtrToStringUTF8(stringPointer);
                return JsonSerializer.Serialize(stringValue);
            }
            finally
            {
                g_free(stringPointer);
            }
        }

        return "null";
    }

    public static string? ConvertUtf8Pointer(IntPtr pointer)
    {
        return pointer == IntPtr.Zero
            ? null
            : Marshal.PtrToStringUTF8(pointer);
    }

    public static string? ConvertUtf8Pointer(IntPtr pointer, int maximumByteCount)
    {
        if (pointer == IntPtr.Zero)
            return null;
        ArgumentOutOfRangeException.ThrowIfNegativeOrZero(maximumByteCount);

        var length = 0;
        while (length < maximumByteCount && Marshal.ReadByte(pointer, length) != 0)
            length++;
        return Marshal.PtrToStringUTF8(pointer, length);
    }

    // GError pointers supplied to GObject signals are borrowed. The emitter
    // still owns them after the managed callback returns.
    public static string GetBorrowedErrorMessage(IntPtr error)
    {
        if (error == IntPtr.Zero) return "Unknown WebKitGTK error.";
        var details = Marshal.PtrToStructure<GError>(error);
        return Marshal.PtrToStringUTF8(details.Message) ?? $"WebKitGTK error {details.Code}.";
    }

    public static string GetErrorMessageAndFree(IntPtr error)
    {
        if (error == IntPtr.Zero)
        {
            return "Unknown WebKitGTK error.";
        }

        try
        {
            var details = Marshal.PtrToStructure<GError>(error);
            return Marshal.PtrToStringUTF8(details.Message) ?? $"WebKitGTK error {details.Code}.";
        }
        finally
        {
            g_error_free(error);
        }
    }

    private static void OnJavaScriptFinished(IntPtr webView, IntPtr asyncResult, IntPtr userData)
    {
        var handle = GCHandle.FromIntPtr(userData);
        var request = (LinuxJavaScriptRequest)handle.Target!;

        try
        {
            try
            {
                var jsResult = webkit_web_view_run_javascript_finish(webView, asyncResult, out var error);
                if (error != IntPtr.Zero)
                {
                    request.TrySetException(new InvalidOperationException(GetErrorMessageAndFree(error)));
                    return;
                }

                try
                {
                    request.TrySetResult(ConvertJavaScriptResultToJson(jsResult));
                }
                finally
                {
                    if (jsResult != IntPtr.Zero)
                    {
                        webkit_javascript_result_unref(jsResult);
                    }
                }
            }
            catch (Exception ex)
            {
                request.TrySetException(ex);
            }
        }
        finally
        {
            request.Dispose();
        }
    }
}
