from __future__ import annotations

from dicodeping.rc2_runtime import install_rc2_patches
from dicodeping.rc3_runtime import install_rc3_patches
from dicodeping.rc4_runtime import install_rc4_patches
from dicodeping.rc5_runtime import install_rc5_patches
from dicodeping.rc6_runtime import install_rc6_patches
from dicodeping.rc7_runtime import install_rc7_patches
from dicodeping.rc8_runtime import install_rc8_patches
from dicodeping.rc9_runtime import install_rc9_patches
from dicodeping.rc10_runtime import install_rc10_patches
from dicodeping.rc11_runtime import install_rc11_patches

for install in (
    install_rc2_patches,
    install_rc3_patches,
    install_rc4_patches,
    install_rc5_patches,
    install_rc6_patches,
    install_rc7_patches,
    install_rc8_patches,
    install_rc9_patches,
    install_rc10_patches,
    install_rc11_patches,
):
    install()

from app import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
