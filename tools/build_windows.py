from __future__ import annotations
import argparse, os, shutil, sys
from pathlib import Path
# Support both `python tools/build_*.py` and `python -m tools.build_*`
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from tools.build_desktop_common import APP_NAME, APP_VERSION, ROOT, prepare_build, pyinstaller_base, run

def build(skip_install: bool=False) -> Path:
    if os.name != "nt": raise RuntimeError("Windows builder must run on Windows")
    engine = prepare_build(skip_install)
    cmd = pyinstaller_base(engine)
    cmd += ["--onefile", "--uac-admin", "--icon", str(ROOT / "assets" / "app.ico"), "--version-file", str(ROOT / "tools" / "windows_version_info.txt"), "--specpath", str(ROOT / "build" / "windows-spec"), str(ROOT / "app.py")]
    run(cmd)
    built = ROOT / "dist" / f"{APP_NAME}.exe"
    if not built.exists(): raise FileNotFoundError(built)
    release = ROOT / "release"; release.mkdir(exist_ok=True)
    out = release / f"{APP_NAME}-v{APP_VERSION}-windows-x64.exe"; shutil.copy2(built, out); return out

def main():
    p=argparse.ArgumentParser(); p.add_argument("--skip-install", action="store_true"); a=p.parse_args()
    try: print(build(a.skip_install)); return 0
    except Exception as e: print(f"Windows build failed: {e}", file=sys.stderr); return 1
if __name__ == "__main__": raise SystemExit(main())
