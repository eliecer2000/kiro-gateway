# -*- coding: utf-8 -*-

"""
T-2.7, T-2.8, T-2.9 — Service file / state dir permission checks.

Spec: service-management §"Requirement: Service file permissions"
Tasks: T-2.7 [red→green] / T-2.8 [red→green] / T-2.9 [red→green]
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from tests.unit.install_script.conftest import REPO_ROOT, stat_mode


def _run_installer(env: dict, install_dir: Path, *args: str) -> subprocess.CompletedProcess:
    full_env = os.environ.copy()
    full_env.update(env)
    cmd = [
        "bash",
        str(REPO_ROOT / "scripts" / "install.sh"),
        "--install-dir",
        str(install_dir),
        *args,
    ]
    return subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        env=full_env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _do_fresh_install(
    tmp_path: Path, stub_curl, stub_launchctl, monkeypatch
) -> Path:
    install_dir = tmp_path / "Library" / "Application Support" / "KiroGateway"
    home = tmp_path
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("UNAME_S", "Darwin")
    env = {
        "HOME": str(home),
        "UNAME_S": "Darwin",
        "PATH": f"{stub_launchctl['bin_dir']}:{stub_curl['bin_dir']}:{os.environ.get('PATH', '')}",
        "STUB_TARBALL_PATH": str(stub_curl["tarball_path"]),
    }
    result = _run_installer(env, install_dir, "--version", "2.5.0", "--insecure")
    assert result.returncode == 0, (
        f"installer failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    return install_dir


def test_state_dir_chmod_700(
    tmp_path: Path, stub_curl, stub_launchctl, monkeypatch
) -> None:
    """T-2.7 — ${INSTALL_DIR}/state MUST be chmod 700."""
    install_dir = _do_fresh_install(tmp_path, stub_curl, stub_launchctl, monkeypatch)
    state_dir = install_dir / "state"
    assert state_dir.is_dir(), f"missing state dir: {state_dir}"
    assert stat_mode(state_dir) == "700", (
        f"state dir mode is {stat_mode(state_dir)}, expected 700"
    )


def test_credentials_json_is_not_created_empty(
    tmp_path: Path, stub_curl, stub_launchctl, monkeypatch
) -> None:
    """Fresh installs leave credentials creation to the .env migration."""
    install_dir = _do_fresh_install(tmp_path, stub_curl, stub_launchctl, monkeypatch)
    creds = install_dir / "state" / "credentials.json"
    assert not creds.exists()


def test_state_json_is_created_by_runtime(
    tmp_path: Path, stub_curl, stub_launchctl, monkeypatch
) -> None:
    """The runtime creates state.json atomically after startup."""
    install_dir = _do_fresh_install(tmp_path, stub_curl, stub_launchctl, monkeypatch)
    s = install_dir / "state" / "state.json"
    assert not s.exists()


def test_env_chmod_600(
    tmp_path: Path, stub_curl, stub_launchctl, monkeypatch
) -> None:
    """T-2.8 (sister) — .env MUST also be chmod 600."""
    install_dir = _do_fresh_install(tmp_path, stub_curl, stub_launchctl, monkeypatch)
    env_file = install_dir / "state" / ".env"
    assert env_file.exists()
    assert stat_mode(env_file) == "600", f".env mode is {stat_mode(env_file)}, expected 600"


def test_logs_dir_chmod_750(
    tmp_path: Path, stub_curl, stub_launchctl, monkeypatch
) -> None:
    """T-2.9 — ${INSTALL_DIR}/logs MUST be chmod 750."""
    install_dir = _do_fresh_install(tmp_path, stub_curl, stub_launchctl, monkeypatch)
    logs = install_dir / "logs"
    assert logs.is_dir(), f"missing logs dir: {logs}"
    assert stat_mode(logs) == "750", (
        f"logs dir mode is {stat_mode(logs)}, expected 750"
    )


def test_plist_chmod_644(
    tmp_path: Path, stub_curl, stub_launchctl, monkeypatch
) -> None:
    """The plist (LaunchAgent) MUST be chmod 644 (readable by launchd)."""
    install_dir = _do_fresh_install(tmp_path, stub_curl, stub_launchctl, monkeypatch)
    plist = tmp_path / "Library" / "LaunchAgents" / "com.jwadow.kiro-gateway.plist"
    assert plist.exists(), f"plist not installed at {plist}"
    assert stat_mode(plist) == "644", f"plist mode is {stat_mode(plist)}, expected 644"
