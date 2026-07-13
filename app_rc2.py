from __future__ import annotations

from dicodeping.rc2_runtime import install_rc2_patches

install_rc2_patches()

from app import main  # noqa: E402  (patches must be installed before app imports its classes)


if __name__ == "__main__":
    raise SystemExit(main())
