# -*- coding: utf-8 -*-

"""
T-1.8 — --install-dir PATH lands the install at the override path, and
state/install.env is written under ${INSTALL_DIR}/state/.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from tests.unit.install_script.conftest import REPO_ROOT


def test_install_dir_override(tmp_path, stub_curl):
    target = tmp_path / "opt" / "kiro"
    env = {
        "HOME": str(tmp_path),
        "UNAME_S": "Darwin",
        "PATH": f"{stub_curl['bin_dir']}:{os.environ.get('PATH', '')}",
        "STUB_TARBALL_PATH": str(stub_curl["tarball_path"]),
    }
    result = subprocess.run(
        ["bash", str(REPO_ROOT / "scripts" / "install.sh"),
         "--install-dir", str(target), "--version", "2.5.0", "--insecure"],
        cwd=str(REPO_ROOT), env=env,
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, f"installer failed: {result.stderr}"
    assert (target / "state" / "install.env").is_file(), "install.env not written"
    content = (target / "state" / "install.env").read_text()
    assert "INSTALL_DIR=" in content
    assert str(target) in content
