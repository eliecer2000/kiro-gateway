# -*- coding: utf-8 -*-

"""
T-2.5 — On macOS, after a fresh install, the post-install summary MUST say
the service is registered but not running.

Spec: service-management §"Scenario: macOS — registered but not running".
Tasks: T-2.5 [red] → T-2.5 [green] → T-2.5 [refactor]
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


def test_post_install_status_registered_not_running_macos(
    tmp_path: Path, stub_curl, stub_launchctl, monkeypatch
) -> None:
    """
    After a fresh install on macOS, the post-install summary MUST print:
        Service is registered but not running. Run: kiro-gateway start

    The `launchctl list` stub returns PID '-' for com.jwadow.kiro-gateway
    (the registered-but-not-running state after `bootstrap` but before
    `start`).
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

    combined = result.stdout + result.stderr
    assert "Service is registered but not running. Run: kiro-gateway start" in combined, (
        f"missing post-install hint in:\n{combined}"
    )


def test_launchctl_bootstrap_was_called(
    tmp_path: Path, stub_curl, stub_launchctl, monkeypatch
) -> None:
    """
    The installer MUST use `launchctl bootstrap gui/$(id -u) <plist>` to
    register the service (NOT `launchctl load`).
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
    _run_installer(env, install_dir, "--version", "2.5.0", "--insecure")

    log = stub_launchctl["log_path"].read_text()
    assert "bootstrap" in log, f"launchctl bootstrap not invoked; log:\n{log}"
    assert "load" not in log or "load_service" not in log, (
        f"launchctl load was invoked; log:\n{log}"
    )
