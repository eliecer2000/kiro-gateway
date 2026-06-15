# -*- coding: utf-8 -*-

"""
T-1.18 — On reinstall, the previous app/ is moved to app.prev/ before the
new version is swapped in.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from tests.unit.install_script.conftest import REPO_ROOT


def test_atomic_swap_creates_app_prev(tmp_path, stub_curl):
    install_dir = tmp_path / "kg"
    state_dir = install_dir / "state"
    state_dir.mkdir(parents=True)
    (state_dir / "install.env").write_text("INSTALL_DIR=x\nVERSION=1.0.0\n")

    # Pre-existing app/.
    pre_app = install_dir / "app"
    pre_app.mkdir(parents=True)
    (pre_app / "previous_marker.txt").write_text("previous")

    env = {
        "HOME": str(tmp_path),
        "UNAME_S": "Darwin",
        "PATH": f"{stub_curl['bin_dir']}:{os.environ.get('PATH', '')}",
        "STUB_TARBALL_PATH": str(stub_curl["tarball_path"]),
    }
    result = subprocess.run(
        ["bash", str(REPO_ROOT / "scripts" / "install.sh"),
         "--install-dir", str(install_dir),
         "--version", "2.5.0", "--insecure"],
        cwd=str(REPO_ROOT), env=env,
        capture_output=True, text=True, timeout=60,
        input="r\n",
    )
    assert result.returncode == 0, f"installer failed: {result.stderr}\nstdout:\n{result.stdout}"

    # app/ contains the new code.
    assert (pre_app / "main.py").is_file()
    # app.prev/ contains the previous marker.
    assert (install_dir / "app.prev" / "previous_marker.txt").read_text() == "previous"
    # app.new/ is gone.
    assert not (install_dir / "app.new").exists()
