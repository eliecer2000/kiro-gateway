# -*- coding: utf-8 -*-

"""
T-1.19 / T-1.20 — venv refresh is gated by the requirements.txt hash.
"""

from __future__ import annotations

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


def test_requirements_unchanged_preserves_venv(tmp_path, stub_curl):
    install_dir = tmp_path / "kg"
    state_dir = install_dir / "state"
    state_dir.mkdir(parents=True)
    (state_dir / "install.env").write_text("INSTALL_DIR=x\nVERSION=1.0.0\n")
    # Pre-existing venv with a sentinel file.
    venv_bin = install_dir / "venv" / "bin"
    venv_bin.mkdir(parents=True)
    sentinel = venv_bin / "sentinel"
    sentinel.write_text("do-not-touch")

    env = {
        "HOME": str(tmp_path),
        "UNAME_S": "Darwin",
        "PATH": f"{stub_curl['bin_dir']}:{os.environ.get('PATH', '')}",
        "STUB_TARBALL_PATH": str(stub_curl["tarball_path"]),
    }
    # Pre-populate the requirements hash to match the stub tarball's
    # requirements.txt (the stub serves the fake_tarball which has
    # "fastapi\nuvicorn\n").
    import hashlib
    req = b"fastapi\nuvicorn\n"
    (state_dir / "requirements.sha256").write_text(hashlib.sha256(req).hexdigest() + "\n")

    result = _run(env, install_dir, "--version", "2.5.0", "--insecure", stdin="r\n")
    assert result.returncode == 0
    # venv sentinel untouched.
    assert sentinel.read_text() == "do-not-touch"


def test_requirements_changed_recreates_venv(tmp_path, stub_curl):
    install_dir = tmp_path / "kg"
    state_dir = install_dir / "state"
    state_dir.mkdir(parents=True)
    (state_dir / "install.env").write_text("INSTALL_DIR=x\nVERSION=1.0.0\n")
    # Old hash that does not match the new requirements.txt.
    (state_dir / "requirements.sha256").write_text("0" * 64 + "\n")

    env = {
        "HOME": str(tmp_path),
        "UNAME_S": "Darwin",
        "PATH": f"{stub_curl['bin_dir']}:{os.environ.get('PATH', '')}",
        "STUB_TARBALL_PATH": str(stub_curl["tarball_path"]),
    }
    result = _run(env, install_dir, "--version", "2.5.0", "--insecure", stdin="r\n")
    assert result.returncode == 0, f"installer failed: {result.stderr}"
    # The venv was re-bootstrapped and the new hash stored.
    new_hash = (state_dir / "requirements.sha256").read_text().strip()
    assert len(new_hash) == 64
    assert new_hash != "0" * 64
    # The new venv has a python symlink.
    assert (install_dir / "venv" / "bin" / "python").exists()
