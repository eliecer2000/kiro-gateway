# -*- coding: utf-8 -*-

"""
T-1.2 — Fresh Linux install produces the documented directory layout, and
honors XDG_DATA_HOME.
"""

from __future__ import annotations

import os
import shutil
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


def test_install_fresh_linux_default_layout(tmp_path, stub_curl):
    """
    Default Linux install root is ${HOME}/.local/share/kiro-gateway/.
    """
    install_dir = tmp_path / ".local" / "share" / "kiro-gateway"
    env = {
        "HOME": str(tmp_path),
        "UNAME_S": "Linux",
        "PATH": f"{stub_curl['bin_dir']}:{os.environ.get('PATH', '')}",
        "STUB_TARBALL_PATH": str(stub_curl["tarball_path"]),
    }
    # Linux preflight will call systemctl via preflight_systemd in T-2.10.
    # The base installer doesn't run preflight_systemd in this slice, so
    # we just need a fake `systemctl` on PATH if anything is invoked.
    result = _run(env, install_dir, "--version", "2.5.0", "--insecure")
    if result.returncode != 0:
        pytest.fail(
            f"installer exited {result.returncode}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )

    for sub in ("app", "venv", "bin", "state", "logs"):
        assert (install_dir / sub).is_dir(), f"missing: {install_dir / sub}"


def test_install_fresh_linux_xdg_data_home_override(tmp_path, stub_curl, monkeypatch):
    """
    When XDG_DATA_HOME is set, the install root lives at
    ${XDG_DATA_HOME}/kiro-gateway/.
    """
    xdg_dir = tmp_path / "srv" / "data"
    xdg_dir.mkdir(parents=True)
    install_dir = xdg_dir / "kiro-gateway"
    env = {
        "HOME": str(tmp_path),
        "UNAME_S": "Linux",
        "XDG_DATA_HOME": str(xdg_dir),
        "PATH": f"{stub_curl['bin_dir']}:{os.environ.get('PATH', '')}",
        "STUB_TARBALL_PATH": str(stub_curl["tarball_path"]),
    }
    result = _run(env, install_dir, "--version", "2.5.0", "--insecure")
    if result.returncode != 0:
        pytest.fail(
            f"installer exited {result.returncode}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )

    for sub in ("app", "venv", "bin", "state", "logs"):
        assert (install_dir / sub).is_dir(), f"missing: {install_dir / sub}"
