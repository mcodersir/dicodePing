from __future__ import annotations

from dicodeping.rc2_runtime import install_rc2_patches
from dicodeping.rc3_runtime import install_rc3_patches
from dicodeping.rc4_runtime import install_rc4_patches
from dicodeping.rc5_runtime import install_rc5_patches
from dicodeping.rc6_runtime import install_rc6_patches

install_rc2_patches()
install_rc3_patches()
install_rc4_patches()
install_rc5_patches()
install_rc6_patches()

from app import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
