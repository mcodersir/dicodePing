using System.Runtime.InteropServices;

namespace GlobalHotKeys;

public class HotKeyManager : IDisposable
{
    private const uint HotKeyMsg = 0x312u;
    private const uint RegisterHotKeyMsg = 0x0400u;     // WM_USER
    private const uint UnregisterHotKeyMsg = 0x0401u;   // WM_USER + 1

    public event Action<HotKey>? HotKeyPressed;         // Event to notify when a hotkey is pressed.

    private readonly Thread _messageLoopThread;         // Store the message loop thread and window handle.
    private readonly IntPtr _hWnd;

    /// <summary>
    /// Constructor initializes the message loop thread and window.
    /// </summary>
    public HotKeyManager()
    {
        // Create a TaskCompletionSource to receive the window handle.
        var tcsHwnd = new TaskCompletionSource<IntPtr>();

        _messageLoopThread = new Thread(new ThreadStart(HotKeyThreadEntry))
        {
            Name = "GlobalHotKeyManager Message Loop"
        };
        _messageLoopThread.Start();
        _hWnd = tcsHwnd.Task.Result;
        return;

        // Thread entry method.
        void HotKeyThreadEntry()
        {
            // Dictionary to keep track of registrations.
            var registrations = new Dictionary<int, HotKey>();

            // Retrieve the module handle.
            var hInstance = NativeFunctions.GetModuleHandle(null);

            // Create the window class from the window procedure.
            var wndProcDelegate = new WndProc(MessageHandler);

            // Convert the WndProc delegate into a structure.
            var wndClassEx = WNDCLASSEX.FromWndProc(wndProcDelegate, out var classNamePtr);

            // Register the window class.
            var registeredClass = NativeFunctions.RegisterClassEx(ref wndClassEx);

            // create the window.
            var localHWnd = NativeFunctions.CreateWindowEx(0, (uint)registeredClass, null, WindowStyle.WS_OVERLAPPED, 0, 0, 640, 480, IntPtr.Zero, IntPtr.Zero, IntPtr.Zero, IntPtr.Zero);

            // Signal that the window has been created.
            tcsHwnd.SetResult(localHWnd);

            // enter message loop.
            MessageLoop(localHWnd);

            // cleanup the resources after wards.
            Cleanup(localHWnd);

            // Keep the delegate alive until after cleanup to prevent GC collection during the message loop.
            GC.KeepAlive(wndProcDelegate);

            return;

            // nextId: find the next free id from 0x0000 to 0xBFFF.
            int? NextId()
            {
                for (var i = 0x0000; i <= 0xBFFF; i++)
                {
                    if (!registrations.ContainsKey(i))
                    {
                        return i;
                    }
                }
                return null;
            }

            // RegisterKey: wrapper for calling RegisterHotKey and updating registrations.
            bool RegisterKey(IntPtr hWnd, VirtualKeyCode key, Modifiers modifiers, int id)
            {
                if (NativeFunctions.RegisterHotKey(hWnd, id, modifiers, key))
                {
                    registrations.Add(id, new HotKey { Id = id, Key = key, Modifiers = modifiers });
                    return true;
                }
                else
                {
                    return false;
                }
            }

            // UnregisterKey: wrapper for calling UnregisterHotKey and updating registrations.
            bool UnregisterKey(IntPtr hWnd, int id)
            {
                var registration = registrations.GetValueOrDefault(id);
                if (registration != null)
                {
                    if (NativeFunctions.UnregisterHotKey(hWnd, registration.Id))
                    {
                        registrations.Remove(id);
                        return true;
                    }
                }
                return false;
            }

            // messageHandler: processes window messages.
            IntPtr MessageHandler(IntPtr hWnd, uint uMsg, IntPtr wParam, IntPtr lParam)
            {
                switch (uMsg)
                {
                    case RegisterHotKeyMsg:
                        {
                            // Extract key and modifiers.
                            var key = (VirtualKeyCode)wParam.ToInt32();
                            var modifiers = (Modifiers)lParam.ToInt32();
                            var id = NextId();
                            if (id.HasValue)
                            {
                                return RegisterKey(hWnd, key, modifiers, id.Value) ? new IntPtr(id.Value) : new IntPtr(-1);
                            }
                            else
                            {
                                return IntPtr.Zero;
                            }
                        }
                    case UnregisterHotKeyMsg:
                        {
                            var id = wParam.ToInt32();
                            return UnregisterKey(hWnd, id) ? new IntPtr(id) : new IntPtr(-1);
                        }
                    case HotKeyMsg:
                        {
                            var registration = registrations.GetValueOrDefault(wParam.ToInt32());
                            if (registration != null)
                            {
                                HotKeyPressed?.Invoke(registration);
                            }
                            return new IntPtr(1);
                        }
                    default:
                        return NativeFunctions.DefWindowProc(hWnd, uMsg, wParam, lParam);
                }
            }

            // messageLoop: processes messages until quit.
            void MessageLoop(IntPtr hWnd)
            {
                var msg = new TagMSG();
                var ret = 0;
                while (((ret = NativeFunctions.GetMessage(ref msg, hWnd, 0u, 0u)) != -1) && (ret != 0))
                {
                    NativeFunctions.TranslateMessage(ref msg);
                    NativeFunctions.DispatchMessage(ref msg);
                }
            }

            // cleanup: unregister any registrations and destroy the window.
            void Cleanup(IntPtr hWnd)
            {
                foreach (var key in registrations.Keys.ToArray())
                {
                    UnregisterKey(hWnd, key);
                }

                NativeFunctions.DestroyWindow(hWnd);
                NativeFunctions.UnregisterClass(classNamePtr, hInstance);
                Marshal.FreeHGlobal(classNamePtr);
            }
        }
    }

    /// <summary>
    /// Register method: registers a hotkey .
    /// </summary>
    /// <param name="key"></param>
    /// <param name="modifiers"></param>
    /// <returns></returns>
    public IRegistration Register(VirtualKeyCode key, Modifiers modifiers)
    {
        // Retrieve the window handle.

        // tell the message loop to register the hotkey.
        var result = NativeFunctions.SendMessage(_hWnd, RegisterHotKeyMsg, new IntPtr((int)key), new IntPtr((int)modifiers));

        // return a disposable that instructs the message loop to unregister the hotkey on disposal.
        return new Registration(_hWnd, result);
    }

    /// <summary>
    /// Dispose method: shuts down the message loop.
    /// </summary>
    public void Dispose()
    {
        // shutdown the message loop.
        NativeFunctions.PostMessage(_hWnd, (uint)WindowMessage.WM_QUIT, IntPtr.Zero, IntPtr.Zero);
        // wait for the shutdown.
        _messageLoopThread.Join();
    }

    /// <summary>
    /// Explicit interface implementation for IDisposable.
    /// </summary>
    void IDisposable.Dispose()
    {
        Dispose();
    }

    private class Registration : IRegistration
    {
        private readonly IntPtr _hWnd;

        public Registration(IntPtr hWnd, IntPtr result)
        {
            _hWnd = hWnd;
            Id = result.ToInt32();
        }

        public bool IsSuccessful => Id != -1;

        public int Id { get; }

        /// <summary>
        /// Dispose method unregisters the hotkey if registration was successful.
        /// </summary>
        public void Dispose()
        {
            if (Id != -1)
            {
                NativeFunctions.SendMessage(_hWnd, UnregisterHotKeyMsg, new IntPtr(Id), IntPtr.Zero);
            }
        }
    }
}
