# -*- coding: utf-8 -*-

"""
T-1.10 — corrupt tarball leaves no app.new/; previous app/ is intact.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from tests.unit.install_script.conftest import REPO_ROOT


def test_atomic_extract_failure_cleans_up(tmp_path):
    """
    Feed a corrupt tarball; assert app.new/ is absent afterward.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "python3").write_text(
        "#!/usr/bin/env bash\n[[ $1 == -V || $1 == --version ]] && echo Python 3.12.0\nexit 0\n"
    )
    (bin_dir / "python3").chmod(0o755)
    (bin_dir / "tar").write_text("#!/usr/bin/env bash\nexit 0\n")
    (bin_dir / "tar").chmod(0o755)
    (bin_dir / "sha256sum").write_text("#!/usr/bin/env bash\nexit 0\n")
    (bin_dir / "sha256sum").chmod(0o755)
    # Stub curl that returns a corrupt tarball (not a valid gzip stream).
    (bin_dir / "curl").write_text(
        "#!/usr/bin/env bash\n"
        "if [[ \"$*\" == *\"-o\"* ]]; then\n"
        "  OUT=\"$(echo \"$*\" | awk -F'-o ' 'NF>1{print $2}' | awk '{print $1}')\"\n"
        "  printf 'this is not a valid tarball' > \"$OUT\"\n"
        "fi\nexit 0\n"
    )
    (bin_dir / "curl").chmod(0o755)

    install_dir = tmp_path / "kg"
    pre_app = install_dir / "app"
    pre_app.mkdir(parents=True)
    (pre_app / "sentinel.txt").write_text("previous-install")

    env = {
        "HOME": str(tmp_path),
        "UNAME_S": "Darwin",
        "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
    }
    result = subprocess.run(
        ["bash", str(REPO_ROOT / "scripts" / "install.sh"),
         "--install-dir", str(install_dir), "--version", "2.5.0", "--insecure"],
        cwd=str(REPO_ROOT), env=env,
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode != 0
    assert not (install_dir / "app.new").exists(), "app.new should be cleaned up on failure"
    assert (pre_app / "sentinel.txt").read_text() == "previous-install"
