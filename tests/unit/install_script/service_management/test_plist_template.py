# -*- coding: utf-8 -*-

"""
T-2.1 — launchd plist template renders with the correct keys.

Spec: service-management §"Requirement: launchd plist template (macOS)"
Tasks: T-2.1 [red] → T-2.1 [green] → T-2.1 [refactor]
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.unit.install_script.conftest import REPO_ROOT
from tests.unit.install_script.service_management.conftest import (
    SERVICE_PLIST,
    render_plist,
)


def test_plist_template_exists() -> None:
    """The plist asset MUST live at scripts/system/kiro-gateway.plist."""
    assert SERVICE_PLIST.exists(), f"missing asset: {SERVICE_PLIST}"


def test_plist_renders_with_correct_keys(tmp_path: Path) -> None:
    """
    The rendered plist MUST declare:
    - RunAtLoad = false
    - KeepAlive = false
    - ProgramArguments = [${INSTALL_DIR}/venv/bin/python, ${INSTALL_DIR}/app/main.py]
    - WorkingDirectory = ${INSTALL_DIR}/state
    - EnvironmentVariables KIRO_GATEWAY_HOME, ACCOUNTS_CONFIG_FILE,
      ACCOUNTS_STATE_FILE
    """
    install_dir = tmp_path / "Library" / "Application Support" / "KiroGateway"
    rendered = render_plist(install_dir)

    # RunAtLoad and KeepAlive are both false (the "not autostart" contract).
    assert "<key>RunAtLoad</key>" in rendered
    assert "<false/>" in rendered
    assert "<key>KeepAlive</key>" in rendered

    # ProgramArguments points at the venv python and runs main.py.
    assert "<key>ProgramArguments</key>" in rendered
    assert f"<string>{install_dir}/venv/bin/python</string>" in rendered
    assert f"<string>{install_dir}/app/main.py</string>" in rendered

    # WorkingDirectory is the state dir (so credentials.json etc. resolve).
    assert "<key>WorkingDirectory</key>" in rendered
    assert f"<string>{install_dir}/state</string>" in rendered

    # EnvironmentVariables include the three required keys.
    assert "<key>EnvironmentVariables</key>" in rendered
    assert "<key>KIRO_GATEWAY_HOME</key>" in rendered
    assert f"<string>{install_dir}</string>" in rendered
    assert "<key>ACCOUNTS_CONFIG_FILE</key>" in rendered
    assert f"<string>{install_dir}/state/credentials.json</string>" in rendered
    assert "<key>ACCOUNTS_STATE_FILE</key>" in rendered
    assert f"<string>{install_dir}/state/state.json</string>" in rendered
    assert "<key>KIRO_ENV_FILE</key>" in rendered
    assert f"<string>{install_dir}/state/.env</string>" in rendered


def test_plist_label_is_com_jwadot_kiro_gateway(tmp_path: Path) -> None:
    """The plist Label MUST be com.jwadow.kiro-gateway (reverse-DNS)."""
    rendered = render_plist(tmp_path / "x")
    assert "<key>Label</key>" in rendered
    assert "<string>com.jwadow.kiro-gateway</string>" in rendered


def test_plist_uses_xmldeclaration(tmp_path: Path) -> None:
    """The plist MUST start with the XML declaration and DOCTYPE."""
    rendered = render_plist(tmp_path / "x")
    assert rendered.startswith("<?xml")
    assert "<!DOCTYPE plist" in rendered
    assert "<plist version=\"1.0\">" in rendered
