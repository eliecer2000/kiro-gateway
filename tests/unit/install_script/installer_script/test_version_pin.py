# -*- coding: utf-8 -*-

"""
T-1.4 — --version X.Y.Z pins the fetched tarball to the vX.Y.Z tag.
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


def test_install_version_pins_tag_url(tmp_path, stub_curl):
    """
    --version 2.4.0 results in fetching kiro-gateway-2.4.0.tar.gz.
    """
    install_dir = tmp_path / "kg"
    env = {
        "HOME": str(tmp_path),
        "UNAME_S": "Darwin",
        "PATH": f"{stub_curl['bin_dir']}:{os.environ.get('PATH', '')}",
        "STUB_TARBALL_PATH": str(stub_curl["tarball_path"]),
    }
    result = _run(env, install_dir, "--version", "2.4.0", "--insecure")
    assert result.returncode == 0, f"installer failed: {result.stderr}"

    # The stub-curl log should record the tarball URL.
    log = stub_curl["calls_log"].read_text()
    assert "releases/download/v2.4.0/kiro-gateway-2.4.0.tar.gz" in log, (
        f"tarball URL not pinned. Calls log:\n{log}"
    )


def test_install_default_version_resolves_to_latest_via_api(tmp_path, stub_curl):
    """
    Without --version, the installer hits the GitHub API and uses
    tag_name=v2.5.0 (our stub).
    """
    install_dir = tmp_path / "kg"
    env = {
        "HOME": str(tmp_path),
        "UNAME_S": "Darwin",
        "PATH": f"{stub_curl['bin_dir']}:{os.environ.get('PATH', '')}",
        "STUB_TARBALL_PATH": str(stub_curl["tarball_path"]),
    }
    result = _run(env, install_dir, "--insecure")
    assert result.returncode == 0, f"installer failed: {result.stderr}"

    log = stub_curl["calls_log"].read_text()
    assert "/releases/latest" in log, f"no /releases/latest call. Log:\n{log}"
    assert "releases/download/v2.5.0/kiro-gateway-2.5.0.tar.gz" in log, (
        f"no versioned release asset fetch. Log:\n{log}"
    )


def test_install_invalid_version_rejected(tmp_path, stub_curl):
    install_dir = tmp_path / "kg"
    env = {
        "HOME": str(tmp_path),
        "UNAME_S": "Darwin",
        "PATH": f"{stub_curl['bin_dir']}:{os.environ.get('PATH', '')}",
        "STUB_TARBALL_PATH": str(stub_curl["tarball_path"]),
    }
    result = _run(env, install_dir, "--version", "not-a-version", "--insecure")
    assert result.returncode != 0
    assert "Invalid" in result.stderr or "Invalid" in result.stdout
