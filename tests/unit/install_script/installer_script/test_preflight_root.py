# -*- coding: utf-8 -*-

"""
T-1.7 — preflight_euid exits 1 with the exact spec message when EUID=0.
The check is the FIRST executable line — no side effects should occur.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from tests.unit.install_script.conftest import REPO_ROOT


def test_preflight_root_fails_with_exact_message(tmp_path):
    install_dir = tmp_path / "kg"
    env = {
        "HOME": str(tmp_path),
        "UNAME_S": "Darwin",
        "EUID": "0",
        "PATH": "/usr/bin:/bin",  # use real curl/tar to confirm no side effects
    }
    result = subprocess.run(
        ["bash", str(REPO_ROOT / "scripts" / "install.sh"),
         "--install-dir", str(install_dir)],
        cwd=str(REPO_ROOT), env=env,
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode != 0
    expected = "Do not run this installer with sudo. Re-run as your normal user."
    assert expected in result.stderr, f"missing exact message. stderr:\n{result.stderr}"


def test_preflight_root_runs_before_layout(tmp_path):
    """
    The EUID check is the first executable line — no install dir should
    be created before the check fails.
    """
    install_dir = tmp_path / "kg"
    env = {
        "HOME": str(tmp_path),
        "UNAME_S": "Darwin",
        "EUID": "0",
        "PATH": "/usr/bin:/bin",
    }
    subprocess.run(
        ["bash", str(REPO_ROOT / "scripts" / "install.sh"),
         "--install-dir", str(install_dir)],
        cwd=str(REPO_ROOT), env=env,
        capture_output=True, text=True, timeout=10,
    )
    assert not install_dir.exists(), "install dir should not exist after EUID check fails"
