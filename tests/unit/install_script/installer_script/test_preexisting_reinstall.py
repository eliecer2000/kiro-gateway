# -*- coding: utf-8 -*-

"""
T-1.9 — pre-existing install with `r` (reinstall) preserves state/.
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


def test_preexisting_reinstall_preserves_credentials(tmp_path, stub_curl):
    """
    Pre-populate state/credentials.json with sentinel content; run with
    stdin `r`; credentials.json must be unchanged byte-for-byte.
    """
    install_dir = tmp_path / "kg"
    state_dir = install_dir / "state"
    state_dir.mkdir(parents=True)
    sentinel = '{"sentinel":"do-not-touch"}\n'
    (state_dir / "credentials.json").write_text(sentinel)

    env = {
        "HOME": str(tmp_path),
        "UNAME_S": "Darwin",
        "PATH": f"{stub_curl['bin_dir']}:{os.environ.get('PATH', '')}",
        "STUB_TARBALL_PATH": str(stub_curl["tarball_path"]),
    }
    result = _run(env, install_dir, "--version", "2.5.0", "--insecure", stdin="r\n")
    assert result.returncode == 0, f"installer failed: {result.stderr}\nstdout:\n{result.stdout}"

    after = (state_dir / "credentials.json").read_text()
    assert after == sentinel, f"credentials.json changed!\nbefore: {sentinel!r}\nafter:  {after!r}"


def test_preexisting_abort_exits_zero_with_no_changes(tmp_path, stub_curl):
    install_dir = tmp_path / "kg"
    state_dir = install_dir / "state"
    state_dir.mkdir(parents=True)
    (state_dir / "install.env").write_text("INSTALL_DIR=x\nVERSION=1.0.0\n")
    sentinel = (state_dir / "install.env").read_text()

    env = {
        "HOME": str(tmp_path),
        "UNAME_S": "Darwin",
        "PATH": f"{stub_curl['bin_dir']}:{os.environ.get('PATH', '')}",
        "STUB_TARBALL_PATH": str(stub_curl["tarball_path"]),
    }
    result = _run(env, install_dir, stdin="a\n")
    assert result.returncode == 0, f"installer failed: {result.stderr}"
    assert (state_dir / "install.env").read_text() == sentinel


def test_preexisting_empty_input_defaults_to_abort(tmp_path, stub_curl):
    install_dir = tmp_path / "kg"
    state_dir = install_dir / "state"
    state_dir.mkdir(parents=True)
    (state_dir / "install.env").write_text("INSTALL_DIR=x\n")
    env = {
        "HOME": str(tmp_path),
        "UNAME_S": "Darwin",
        "PATH": f"{stub_curl['bin_dir']}:{os.environ.get('PATH', '')}",
        "STUB_TARBALL_PATH": str(stub_curl["tarball_path"]),
    }
    # Empty input → defaults to abort.
    result = _run(env, install_dir, stdin="\n")
    assert result.returncode == 0
