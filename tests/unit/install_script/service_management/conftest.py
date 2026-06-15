# -*- coding: utf-8 -*-

"""
Shared fixtures for service-management unit tests.

The conftest provides:
- `render_plist(install_dir)`: read scripts/system/kiro-gateway.plist and
  substitute ${INSTALL_DIR} and ${HOME} placeholders. Used by every test
  that asserts on the rendered plist content.
- `render_unit(install_dir, home)`: same for scripts/system/kiro-gateway.service.
- A `stub_systemd_user` fixture that places an empty `systemctl` on PATH so
  `command -v systemctl` succeeds but the installer's preflight_systemd
  branch is exercised.
- A `stub_launchctl` fixture that records launchctl calls and returns
  canned output for `launchctl list` / `launchctl print`.
"""

from __future__ import annotations

import os
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPTS_DIR = REPO_ROOT / "scripts"
SERVICE_PLIST = SCRIPTS_DIR / "system" / "kiro-gateway.plist"
SERVICE_UNIT = SCRIPTS_DIR / "system" / "kiro-gateway.service"


def render_plist(install_dir: str | Path) -> str:
    """Read the plist template and substitute ${INSTALL_DIR} and ${HOME}."""
    text = SERVICE_PLIST.read_text()
    text = text.replace("${INSTALL_DIR}", str(install_dir))
    text = text.replace("${HOME}", str(Path.home()))
    return text


def render_unit(install_dir: str | Path, home: str | Path) -> str:
    """Read the unit template and substitute ${INSTALL_DIR} and ${HOME}."""
    text = SERVICE_UNIT.read_text()
    text = text.replace("${INSTALL_DIR}", str(install_dir))
    text = text.replace("${HOME}", str(home))
    return text


@pytest.fixture
def stub_systemd_user(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """
    Place a stub `systemctl` on PATH that:
    - returns 0 for `--user show-environment` (so the preflight gate passes)
    - returns "inactive (dead)" for `--user is-active kiro-gateway`
    - records every call into a log file at $STUB_SYSTEMCTL_LOG
    - returns 0 for `daemon-reload`

    Returns a dict with the bin dir and the log path.
    """
    bin_dir = tmp_path / "systemd-stub-bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    log_path = tmp_path / "systemctl-calls.log"

    systemctl_script = textwrap.dedent(
        f"""\
        #!/usr/bin/env bash
        # Stub systemctl for service-management tests.
        set -uo pipefail
        echo "$@" >> "{log_path}"

        # Surface "inactive (dead)" for is-active probes.
        if [[ "$1" == "--user" ]] && [[ "$2" == "is-active" ]]; then
          echo "inactive"
          exit 0
        fi

        if [[ "$1" == "--user" ]] && [[ "$2" == "status" ]]; then
          echo "kiro-gateway.service - Kiro Gateway"
          echo "   Loaded: loaded"
          echo "   Active: inactive (dead)"
          exit 0
        fi

        if [[ "$1" == "--user" ]] && [[ "$2" == "show-environment" ]]; then
          echo "PATH=/usr/bin"
          exit 0
        fi

        if [[ "$1" == "--user" ]] && [[ "$2" == "daemon-reload" ]]; then
          exit 0
        fi

        exit 0
        """
    )
    systemctl_path = bin_dir / "systemctl"
    systemctl_path.write_text(systemctl_script)
    systemctl_path.chmod(0o755)

    new_path = f"{bin_dir}:{os.environ.get('PATH', '')}"
    monkeypatch.setenv("PATH", new_path)
    monkeypatch.setenv("STUB_SYSTEMCTL_LOG", str(log_path))
    monkeypatch.setenv("STUB_SYSTEMCTL_BIN", str(bin_dir))

    return {"bin_dir": bin_dir, "log_path": log_path}


@pytest.fixture
def stub_launchctl(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """
    Place a stub `launchctl` on PATH that:
    - records every invocation into a log file
    - returns "PID=\"-\" ... com.jwadow.kiro-gateway" for `list | grep`
    - succeeds for `bootstrap` / `bootout` / `print`
    """
    bin_dir = tmp_path / "launchctl-stub-bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    log_path = tmp_path / "launchctl-calls.log"

    launchctl_script = textwrap.dedent(
        f"""\
        #!/usr/bin/env bash
        # Stub launchctl for service-management tests.
        set -uo pipefail
        echo "$@" >> "{log_path}"

        if [[ "$1" == "list" ]]; then
          # Mimic launchctl list output: the row for the registered plist
          # shows PID "-" (registered but not running).
          printf '%s\\n' "PID	Status	Label"
          printf '%s\\n' "-	0	com.jwadow.kiro-gateway"
          exit 0
        fi

        if [[ "$1" == "print" ]]; then
          # Mimic `launchctl print gui/<uid>/<label>` after `bootstrap` but
          # before `start`: state = waiting.
          printf 'state = waiting\\n'
          exit 0
        fi

        if [[ "$1" == "bootstrap" ]] || [[ "$1" == "bootout" ]]; then
          exit 0
        fi

        exit 0
        """
    )
    lc_path = bin_dir / "launchctl"
    lc_path.write_text(launchctl_script)
    lc_path.chmod(0o755)

    new_path = f"{bin_dir}:{os.environ.get('PATH', '')}"
    monkeypatch.setenv("PATH", new_path)
    monkeypatch.setenv("STUB_LAUNCHCTL_LOG", str(log_path))

    return {"bin_dir": bin_dir, "log_path": log_path}
