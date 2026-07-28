from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_all_desktop_builders_package_the_rc17_runtime_wrapper() -> None:
    for relative in (
        "tools/build_windows.py",
        "tools/build_linux.py",
        "tools/build_macos.py",
    ):
        builder = read(relative)
        assert 'entrypoint = root / "app_v190_rc17.py"' in builder
        assert 'entrypoint = root / "app.py"' not in builder

    spec = read("dicodePing.spec")
    assert '[str(root / "app_v190_rc17.py")]' in spec


def test_rc17_wrapper_installs_discovery_runtime_before_importing_app() -> None:
    wrapper = read("app_v190_rc17.py")
    assert "from dicodeping.rc7_runtime import install_rc7_patches" in wrapper
    assert "install_rc7_patches," in wrapper
    assert wrapper.index("install_rc7_patches,") < wrapper.index("from app import main")
    assert 'if __name__ == "__main__":' in wrapper
