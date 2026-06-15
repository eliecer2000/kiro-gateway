# -*- coding: utf-8 -*-

"""
T-2.6 — On Linux, after a fresh install, the post-install summary MUST say
the service is registered but not running.

Spec: service-management §"Scenario: Linux — inactive after install".
Tasks: T-2.6 [red] → T-2.6 [green] → T-2.6 [refactor]
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from tests.unit.install_script.conftest import REPO_ROOT


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


def test_post_install_status_inactive_linux(
    tmp_path: Path, stub_curl, stub_systemd_user, monkeypatch
) -> None:
    """
    On Linux, after a fresh install, the post-install summary MUST print
    the same hint string. The systemd stub returns "inactive" for
    `is-active kiro-gateway`.
    """
    install_dir = tmp_path / ".local" / "share" / "kiro-gateway"
    home = tmp_path
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("UNAME_S", "Linux")
    env = {
        "HOME": str(home),
        "UNAME_S": "Linux",
        "PATH": f"{stub_systemd_user['bin_dir']}:{stub_curl['bin_dir']}:{os.environ.get('PATH', '')}",
        "STUB_TARBALL_PATH": str(stub_curl["tarball_path"]),
    }
    result = _run_installer(env, install_dir, "--version", "2.5.0", "--insecure")
    assert result.returncode == 0, (
        f"installer failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )

    combined = result.stdout + result.stderr
    assert "Service is registered but not running. Run: kiro-gateway start" in combined, (
        f"missing post-install hint in:\n{combined}"
    )


def test_daemon_reload_was_called(
    tmp_path: Path, stub_curl, stub_systemd_user, monkeypatch
) -> None:
    """The installer MUST run `systemctl --user daemon-reload` (not enable)."""
    install_dir = tmp_path / ".local" / "share" / "kiro-gateway"
    home = tmp_path
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("UNAME_S", "Linux")
    env = {
        "HOME": str(home),
        "UNAME_S": "Linux",
        "PATH": f"{stub_systemd_user['bin_dir']}:{stub_curl['bin_dir']}:{os.environ.get('PATH', '')}",
        "STUB_TARBALL_PATH": str(stub_curl["tarball_path"]),
    }
    _run_installer(env, install_dir, "--version", "2.5.0", "--insecure")

    log = stub_systemd_user["log_path"].read_text()
    assert "daemon-reload" in log, f"daemon-reload not called; log:\n{log}"
    # No `enable` line should appear.
    for line in log.splitlines():
        assert "enable" not in line, f"forbidden 'enable' in systemctl call: {line!r}"
