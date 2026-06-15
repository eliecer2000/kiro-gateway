# -*- coding: utf-8 -*-

"""
T-1.3 — --help / -h print usage and exit 0 BEFORE preflight.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from tests.unit.install_script.conftest import REPO_ROOT


def _run(*args: str, env_extra: dict | None = None) -> subprocess.CompletedProcess:
    full_env = os.environ.copy()
    if env_extra:
        full_env.update(env_extra)
    return subprocess.run(
        ["bash", str(REPO_ROOT / "scripts" / "install.sh"), *args],
        cwd=str(REPO_ROOT), env=full_env,
        capture_output=True, text=True, timeout=10,
    )


def test_install_help_long_form_exits_zero():
    result = _run("--help")
    assert result.returncode == 0, f"exit {result.returncode}: {result.stderr}"
    # The usage text mentions every documented flag.
    for flag in ["--help", "--version", "--install-dir", "--insecure",
                 "install", "update", "uninstall", "--rollback"]:
        assert flag in result.stdout, f"usage missing flag: {flag}"


def test_install_help_short_form_exits_zero():
    result = _run("-h")
    assert result.returncode == 0
    assert "--help" in result.stdout


def test_install_help_runs_without_euid_check():
    """
    T-1.7 will check that EUID=0 is rejected; --help must short-circuit
    BEFORE preflight so it can be used as a quick reference.
    """
    # If we set EUID=0, --help should still exit 0.
    result = _run("--help", env_extra={"EUID": "0"})
    assert result.returncode == 0
    assert "Usage" in result.stdout or "--help" in result.stdout
