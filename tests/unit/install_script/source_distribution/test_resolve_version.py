# -*- coding: utf-8 -*-

"""
T-1.13 / T-1.14 — Default version resolves to latest via the GitHub API;
--version X.Y.Z pins the tag.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from tests.unit.install_script.conftest import REPO_ROOT


def _run(env: dict, install_dir: Path, *args: str) -> subprocess.CompletedProcess:
    full_env = os.environ.copy()
    full_env.update(env)
    return subprocess.run(
        ["bash", str(REPO_ROOT / "scripts" / "install.sh"),
         "--install-dir", str(install_dir), *args],
        cwd=str(REPO_ROOT), env=full_env,
        capture_output=True, text=True, timeout=60,
    )


def test_default_version_resolves_to_latest(tmp_path, stub_curl):
    install_dir = tmp_path / "kg"
    env = {
        "HOME": str(tmp_path),
        "UNAME_S": "Darwin",
        "PATH": f"{stub_curl['bin_dir']}:{os.environ.get('PATH', '')}",
        "STUB_TARBALL_PATH": str(stub_curl["tarball_path"]),
    }
    result = _run(env, install_dir, "--insecure")
    assert result.returncode == 0
    log = stub_curl["calls_log"].read_text()
    assert "v2.5.0.tar.gz" in log


def test_version_flag_pins_tag(tmp_path, stub_curl):
    install_dir = tmp_path / "kg"
    env = {
        "HOME": str(tmp_path),
        "UNAME_S": "Darwin",
        "PATH": f"{stub_curl['bin_dir']}:{os.environ.get('PATH', '')}",
        "STUB_TARBALL_PATH": str(stub_curl["tarball_path"]),
    }
    result = _run(env, install_dir, "--version", "2.4.0", "--insecure")
    assert result.returncode == 0
    log = stub_curl["calls_log"].read_text()
    assert "v2.4.0.tar.gz" in log
    assert "v2.5.0.tar.gz" not in log
