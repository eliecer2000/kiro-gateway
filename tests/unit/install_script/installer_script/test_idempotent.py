# -*- coding: utf-8 -*-

"""
T-1.12 — Second run with default answer aborts; state/ is byte-identical.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

import pytest

from tests.unit.install_script.conftest import REPO_ROOT


def _run(env: dict, install_dir: Path, *args: str, stdin: str = "") -> subprocess.CompletedProcess:
    full_env = os.environ.copy()
    full_env.update(env)
    return subprocess.run(
        ["bash", str(REPO_ROOT / "scripts" / "install.sh"),
         "--install-dir", str(install_dir), *args],
        cwd=str(REPO_ROOT), env=full_env,
        capture_output=True, text=True, timeout=60,
        input=stdin,
    )


def test_idempotent_second_run_aborts(tmp_path, stub_curl):
    install_dir = tmp_path / "kg"
    env = {
        "HOME": str(tmp_path),
        "UNAME_S": "Darwin",
        "PATH": f"{stub_curl['bin_dir']}:{os.environ.get('PATH', '')}",
        "STUB_TARBALL_PATH": str(stub_curl["tarball_path"]),
    }
    # First run completes.
    r1 = _run(env, install_dir, "--version", "2.5.0", "--insecure")
    assert r1.returncode == 0, f"first run failed: {r1.stderr}"
    env_path = install_dir / "state" / "install.env"
    sha_before = hashlib.sha256(env_path.read_bytes()).hexdigest()

    # Second run with default answer (empty) aborts without changes.
    r2 = _run(env, install_dir, "--version", "2.5.0", "--insecure", stdin="\n")
    assert r2.returncode == 0, f"second run should abort 0: {r2.stderr}"

    sha_after = hashlib.sha256(env_path.read_bytes()).hexdigest()
    assert sha_before == sha_after, "state/install.env was modified on second run"
