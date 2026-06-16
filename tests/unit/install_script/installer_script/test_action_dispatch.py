# -*- coding: utf-8 -*-

"""Regression coverage for installer lifecycle action dispatch."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from tests.unit.install_script.conftest import REPO_ROOT


def _prepare_installed_control(tmp_path: Path) -> tuple[Path, Path]:
    install_dir = tmp_path / "install"
    (install_dir / "state").mkdir(parents=True)
    (install_dir / "state" / "install.env").write_text(
        f'INSTALL_DIR="{install_dir}"\nVERSION=2.5.0\nPLATFORM=Linux\n'
    )
    (install_dir / "bin").mkdir()
    calls = tmp_path / "control-calls.log"
    control = install_dir / "bin" / "kiro-gateway"
    control.write_text(f'#!/usr/bin/env bash\nprintf "%s\\n" "$*" >> "{calls}"\n')
    control.chmod(0o755)
    return install_dir, calls


def _run(install_dir: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update({"HOME": str(install_dir.parent), "UNAME_S": "Linux"})
    return subprocess.run(
        [
            "bash",
            str(REPO_ROOT / "scripts" / "install.sh"),
            "--install-dir",
            str(install_dir),
            *args,
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_update_dispatches_installed_control_command(tmp_path: Path) -> None:
    install_dir, calls = _prepare_installed_control(tmp_path)
    result = _run(install_dir, "update")
    assert result.returncode == 0, result.stderr
    assert calls.read_text() == "update\n"


def test_rollback_dispatches_update_rollback(tmp_path: Path) -> None:
    install_dir, calls = _prepare_installed_control(tmp_path)
    result = _run(install_dir, "--rollback")
    assert result.returncode == 0, result.stderr
    assert calls.read_text() == "update --rollback\n"


def test_uninstall_dispatches_installed_control_command(tmp_path: Path) -> None:
    install_dir, calls = _prepare_installed_control(tmp_path)
    result = _run(install_dir, "uninstall")
    assert result.returncode == 0, result.stderr
    assert calls.read_text() == "uninstall\n"


def test_action_without_control_command_fails_actionably(tmp_path: Path) -> None:
    install_dir = tmp_path / "missing"
    result = _run(install_dir, "update")
    assert result.returncode != 0
    assert "installed control command" in result.stderr
    assert str(install_dir) in result.stderr
