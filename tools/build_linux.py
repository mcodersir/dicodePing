from __future__ import annotations
import argparse, platform, shutil, sys, tarfile
from pathlib import Path
# Support both `python tools/build_*.py` and `python -m tools.build_*`
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from tools.build_desktop_common import APP_NAME, APP_VERSION, ROOT, prepare_build, pyinstaller_base, run

def build(skip_install: bool=False) -> Path:
    if not sys.platform.startswith("linux"): raise RuntimeError("Linux builder must run on Linux")
    engine=prepare_build(skip_install); spec=ROOT/"build"/"linux-spec"; spec.mkdir(parents=True,exist_ok=True)
    cmd=pyinstaller_base(engine)+["--onefile","--specpath",str(spec),str(ROOT/"app.py")]; run(cmd)
    built=ROOT/"dist"/APP_NAME
    if not built.exists(): raise FileNotFoundError(built)
    arch="arm64" if platform.machine().lower() in {"arm64","aarch64"} else "x86_64"
    name=f"{APP_NAME}-v{APP_VERSION}-linux-{arch}"; stage=ROOT/"build"/name; shutil.rmtree(stage,ignore_errors=True); stage.mkdir(parents=True)
    shutil.copy2(built,stage/APP_NAME); (stage/APP_NAME).chmod(0o755)
    for rel in ("packaging/linux/run-dicodePing.sh","packaging/linux/README-LINUX.txt","packaging/linux/dicodePing.desktop","LICENSE","THIRD_PARTY_NOTICES.md"):
        src=ROOT/rel
        if src.exists(): shutil.copy2(src,stage/src.name)
    release=ROOT/"release"; release.mkdir(exist_ok=True); out=release/f"{name}.tar.gz"
    with tarfile.open(out,"w:gz") as tf: tf.add(stage,arcname=name)
    return out

def main():
    p=argparse.ArgumentParser(); p.add_argument("--skip-install",action="store_true"); a=p.parse_args()
    try: print(build(a.skip_install)); return 0
    except Exception as e: print(f"Linux build failed: {e}",file=sys.stderr); return 1
if __name__=="__main__": raise SystemExit(main())
