# -*- coding: utf-8 -*-

"""
T-1.17 — Post-extract, the four excludes (.git, tests, docs, .github) are
gone; LICENSE remains.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from tests.unit.install_script.conftest import REPO_ROOT


def test_tarball_excludes_removed(tmp_path, stub_curl):
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

    app = install_dir / "app"
    for excluded in (".git", "tests", "docs", ".github"):
        assert not (app / excluded).exists(), f"{excluded} should be removed"
    assert (app / "LICENSE").is_file(), "LICENSE should be present"
