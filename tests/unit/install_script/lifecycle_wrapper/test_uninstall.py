# -*- coding: utf-8 -*-

"""
Tests for the `uninstall` subcommand (T-3.5).

The wrapper must:
- Always stop the service and remove the plist/unit + symlink.
- On `y` (or `Y`): also delete the install dir.
- On `N` (or default): preserve the install dir.
"""

from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path

import pytest

WRAPPER = Path(__file__).resolve().parents[4] / "scripts" / "kiro-gateway"


def _write_stub(tmp_path: Path, name: str, body: str) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    p = bin_dir / name
    p.write_text(textwrap.dedent(body))
    p.chmod(0o755)
    return p


def test_wrapper_uninstall_y_removes_install_dir(tmp_path, monkeypatch, installed_env):
    """
    GIVEN the user types `y` at the prompt
    WHEN `kiro-gateway uninstall` is invoked
    THEN the install dir is removed.
    """
    log = tmp_path / "svc.log"
    _write_stub(
        tmp_path,
        "launchctl",
        f"""\
        #!/usr/bin/env bash
        echo "$@" >> "{log}"
        exit 0
        """,
    )
    monkeypatch.setenv("PATH", f"{tmp_path}/bin:{os.environ.get('PATH', '')}")
    monkeypatch.setenv("UNAME_S", "Darwin")
    monkeypatch.setenv("HOME", str(installed_env.parent / "home"))

    assert installed_env.exists()

    out = subprocess.run(
        ["bash", str(WRAPPER), "uninstall"],
        env=os.environ.copy(),
        input="y\n",
        capture_output=True,
        text=True,
    )
    assert out.returncode == 0, (
        f"exit={out.returncode}\nstdout={out.stdout!r}\nstderr={out.stderr!r}"
    )
    # The install dir should be gone.
    assert not installed_env.exists(), f"install dir {installed_env} should be removed"


def test_wrapper_uninstall_n_preserves_install_dir(tmp_path, monkeypatch, installed_env):
    """
    GIVEN the user types `N` (or empty) at the prompt
    WHEN `kiro-gateway uninstall` is invoked
    THEN the install dir is preserved.
    """
    log = tmp_path / "svc.log"
    _write_stub(
        tmp_path,
        "launchctl",
        f"""\
        #!/usr/bin/env bash
        echo "$@" >> "{log}"
        exit 0
        """,
    )
    monkeypatch.setenv("PATH", f"{tmp_path}/bin:{os.environ.get('PATH', '')}")
    monkeypatch.setenv("UNAME_S", "Darwin")
    monkeypatch.setenv("HOME", str(installed_env.parent / "home"))

    assert installed_env.exists()

    out = subprocess.run(
        ["bash", str(WRAPPER), "uninstall"],
        env=os.environ.copy(),
        input="N\n",
        capture_output=True,
        text=True,
    )
    assert out.returncode == 0, (
        f"exit={out.returncode}\nstdout={out.stdout!r}\nstderr={out.stderr!r}"
    )
    # Install dir should still exist.
    assert installed_env.exists(), f"install dir {installed_env} should be preserved"
    # The plist was removed (we didn't place one, so just assert the launchctl log).
    log_content = log.read_text() if log.exists() else ""
    assert "bootout" in log_content, f"expected bootout in launchctl log; got: {log_content!r}"
