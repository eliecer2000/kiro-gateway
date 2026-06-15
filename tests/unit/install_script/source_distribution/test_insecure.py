# -*- coding: utf-8 -*-

"""
T-1.16 — --insecure skips SHA256 verification and prints the warning.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from tests.unit.install_script.conftest import REPO_ROOT


def test_insecure_skips_verification(tmp_path, stub_curl):
    install_dir = tmp_path / "kg"
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
    )
    assert result.returncode == 0, f"installer failed: {result.stderr}"
    assert "skipping SHA256 verification" in result.stderr
    assert (install_dir / "app").is_dir()
