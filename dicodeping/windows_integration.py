from __future__ import annotations

import os
from pathlib import Path
from typing import Any

# Keep native icon handles alive for the lifetime of the process. Windows may keep
# referencing the handles after WM_SETICON returns; the process will reclaim them
# automatically on exit.
_NATIVE_ICON_HANDLES: list[int] = []


def set_process_app_user_model_id(app_id: str) -> bool:
    """Assign a stable Windows taskbar identity before any top-level window exists."""
    if os.name != "nt" or not app_id.strip():
        return False

    try:
        import ctypes

        shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        function = shell32.SetCurrentProcessExplicitAppUserModelID
        function.argtypes = [ctypes.c_wchar_p]
        function.restype = ctypes.c_long
        # HRESULT values with the high bit clear indicate success.
        return int(function(app_id)) >= 0
    except Exception:
        return False


def apply_native_window_icon(window: Any, icon_path: str | Path) -> bool:
    """Set the Win32 large/small icons used by taskbar, Alt+Tab, and title UI.

    Qt's QWindow icon is retained as the portable path. This native fallback is
    intentionally Windows-only because frameless PySide windows can otherwise
    inherit a generic executable icon on some Windows 10/11 shell configurations.
    """
    if os.name != "nt":
        return False

    path = Path(icon_path)
    if not path.is_file():
        return False

    try:
        import ctypes
        from ctypes import wintypes

        hwnd = int(window.winId())
        if hwnd <= 0:
            return False

        user32 = ctypes.WinDLL("user32", use_last_error=True)

        load_image = user32.LoadImageW
        load_image.argtypes = [
            wintypes.HINSTANCE,
            wintypes.LPCWSTR,
            wintypes.UINT,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.UINT,
        ]
        load_image.restype = wintypes.HANDLE

        send_message = user32.SendMessageW
        send_message.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        send_message.restype = wintypes.LPARAM

        get_system_metrics = user32.GetSystemMetrics
        get_system_metrics.argtypes = [ctypes.c_int]
        get_system_metrics.restype = ctypes.c_int

        image_icon = 1
        lr_load_from_file = 0x0010
        wm_seticon = 0x0080
        icon_small = 0
        icon_big = 1
        sm_cxicon, sm_cyicon = 11, 12
        sm_cxsmicon, sm_cysmicon = 49, 50

        requests = (
            (icon_big, get_system_metrics(sm_cxicon), get_system_metrics(sm_cyicon)),
            (icon_small, get_system_metrics(sm_cxsmicon), get_system_metrics(sm_cysmicon)),
        )

        applied = False
        for icon_kind, width, height in requests:
            handle = load_image(
                None,
                str(path.resolve()),
                image_icon,
                max(1, width),
                max(1, height),
                lr_load_from_file,
            )
            if not handle:
                continue
            native_handle = int(handle)
            _NATIVE_ICON_HANDLES.append(native_handle)
            send_message(hwnd, wm_seticon, icon_kind, native_handle)
            applied = True

        return applied
    except Exception:
        return False
