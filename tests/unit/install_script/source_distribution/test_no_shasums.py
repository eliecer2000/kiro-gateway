# -*- coding: utf-8 -*-

"""
T-1.15 — When SHA256SUMS is not reachable, the installer exits 1 with the
exact documented message and performs no extraction.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from tests.unit.install_script.conftest import REPO_ROOT


def test_no_shasums_fails_closed(tmp_path, stub_curl):
    install_dir = tmp_path / "kg"
    env = {
        "HOME": str(tmp_path),
        "UNAME_S": "Darwin",
        "PATH": f"{stub_curl['bin_dir']}:{os.environ.get('PATH', '')}",
        "STUB_TARBALL_PATH": str(stub_curl["tarball_path"]),
    }
    result = subprocess.run(
        ["bash", str(REPO_ROOT / "scripts" / "install.sh"),
         "--install-dir", str(install_dir), "--version", "2.5.0"],
        cwd=str(REPO_ROOT), env=env,
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode != 0
    assert "No SHA256SUMS available. Re-run with --insecure to skip verification." in result.stderr
    # No extraction happened.
    assert not (install_dir / "app").exists()
