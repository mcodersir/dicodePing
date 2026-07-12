# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

root = Path(SPECPATH)
assets = root / "assets"
core = root / "core"

a = Analysis(
    [str(root / "app.py")],
    pathex=[str(root)],
    binaries=[
        (str(core / "xray.exe"), "core"),
        (str(core / "wintun.dll"), "core"),
    ],
    datas=[
        (str(assets), "assets"),
        (str(core / "geoip.dat"), "core"),
        (str(core / "geosite.dat"), "core"),
    ],
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
    a.binaries,
    a.datas,
    [],
    name="dicodePing",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
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
