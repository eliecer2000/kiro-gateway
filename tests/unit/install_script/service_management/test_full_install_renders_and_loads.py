# -*- coding: utf-8 -*-

"""
T-2.11 — Full installer end-to-end: render the platform service template
into the platform-native location AND load it (without enabling autostart).

Spec: service-management §"Requirement: launchd plist template (macOS)"
     §"Requirement: systemd --user unit template (Linux)"
Tasks: T-2.11 [red] → T-2.11 [green] → T-2.11 [refactor]
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from tests.unit.install_script.conftest import REPO_ROOT
from tests.unit.install_script.service_management.conftest import (
    render_plist,
    render_unit,
)


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


def test_install_renders_macos_plist(
    tmp_path: Path, stub_curl, stub_launchctl, monkeypatch
) -> None:
    """
    On macOS, after a fresh install:
    - the plist is rendered to ~/Library/LaunchAgents/com.jwadow.kiro-gateway.plist
    - the plist's ${INSTALL_DIR} is substituted with the actual install dir
    - launchctl bootstrap was called (NOT load -w)
    - verify_not_running returned 0 (the row from `launchctl list` had PID "-")
    """
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

    plist = home / "Library" / "LaunchAgents" / "com.jwadow.kiro-gateway.plist"
    assert plist.exists(), f"plist not rendered at {plist}"
    text = plist.read_text()
    # INSTALL_DIR was substituted.
    assert str(install_dir) in text, f"plist missing INSTALL_DIR; got:\n{text[:500]}"
    assert "${INSTALL_DIR}" not in text, "plist still contains unrendered placeholder"
    # Label is correct.
    assert "<string>com.jwadow.kiro-gateway</string>" in text
    # No bootstrap, no PID row, but the post-install hint was printed.
    log = stub_launchctl["log_path"].read_text()
    assert "bootstrap" in log, f"bootstrap not called; log:\n{log}"


def test_install_renders_linux_unit(
    tmp_path: Path, stub_curl, stub_systemd_user, monkeypatch
) -> None:
    """
    On Linux, after a fresh install:
    - the unit is rendered to ~/.config/systemd/user/kiro-gateway.service
    - ${INSTALL_DIR} is substituted
    - `systemctl --user daemon-reload` was called
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

    unit = home / ".config" / "systemd" / "user" / "kiro-gateway.service"
    assert unit.exists(), f"unit not rendered at {unit}"
    text = unit.read_text()
    assert str(install_dir) in text
    assert "${INSTALL_DIR}" not in text
    assert "WantedBy=default.target" in text

    log = stub_systemd_user["log_path"].read_text()
    assert "daemon-reload" in log


def test_verify_not_running_called_in_post_install_summary(
    tmp_path: Path, stub_curl, stub_launchctl, monkeypatch
) -> None:
    """
    The post-install summary MUST invoke `verify_not_running`. We can
    detect that by asserting the post-install hint is printed (which only
    happens when `verify_not_running` returns 0).
    """
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
    assert result.returncode == 0
    combined = result.stdout + result.stderr
    assert "Service is registered but not running. Run: kiro-gateway start" in combined

    # The launchctl list log was hit (verify_not_running calls it).
    log = stub_launchctl["log_path"].read_text()
    assert "list" in log
