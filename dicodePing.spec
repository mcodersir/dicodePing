# -*- mode: python ; coding: utf-8 -*-
"""Legacy PyInstaller spec for local, transparent onedir builds.

Public release packages are produced by tools/build_windows.py, build_linux.py,
or build_macos.py so platform signing can be applied. Required tunnel executables and verified UI assets are prepared by the platform builders before PyInstaller runs.
"""
from pathlib import Path

root = Path(SPECPATH)
assets = root / "assets"

a = Analysis(
    [str(root / "app_v200.py")],
    pathex=[str(root)],
    binaries=[],
    datas=[(str(assets), "assets")],
    hiddenimports=["PySide6.QtSvg"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="dicodePing",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    uac_admin=True,
    icon=str(assets / "app.ico"),
    version=str(root / "tools" / "windows_version_info.txt"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="dicodePing",
)
