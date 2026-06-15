# -*- coding: utf-8 -*-

"""
T-2.2 — systemd --user unit template renders with the correct keys.

Spec: service-management §"Requirement: systemd --user unit template (Linux)"
Tasks: T-2.2 [red] → T-2.2 [green] → T-2.2 [refactor]
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.unit.install_script.service_management.conftest import (
    SERVICE_UNIT,
    render_unit,
)


def test_unit_template_exists() -> None:
    """The unit asset MUST live at scripts/system/kiro-gateway.service."""
    assert SERVICE_UNIT.exists(), f"missing asset: {SERVICE_UNIT}"


def test_unit_renders_with_correct_keys(tmp_path: Path) -> None:
    """
    The rendered unit MUST declare:
    - [Service] ExecStart = ${INSTALL_DIR}/venv/bin/python main.py
    - [Service] WorkingDirectory = ${INSTALL_DIR}/state
    - [Install] WantedBy = default.target
    - Environment=KIRO_GATEWAY_HOME, ACCOUNTS_CONFIG_FILE, ACCOUNTS_STATE_FILE
    """
    install_dir = tmp_path / ".local" / "share" / "kiro-gateway"
    home = tmp_path
    rendered = render_unit(install_dir, home)

    # [Unit] description is required for `systemctl status` readability.
    assert "[Unit]" in rendered
    assert "Description=Kiro Gateway" in rendered

    # [Service] section: ExecStart, WorkingDirectory, Environment.
    assert "[Service]" in rendered
    assert "ExecStart=" in rendered
    assert f"{install_dir}/venv/bin/python main.py" in rendered
    assert "WorkingDirectory=" in rendered
    assert f"{install_dir}/state" in rendered

    # The three required env vars.
    assert "Environment=KIRO_GATEWAY_HOME=" in rendered
    assert f"Environment=KIRO_GATEWAY_HOME={install_dir}" in rendered
    assert "Environment=ACCOUNTS_CONFIG_FILE=" in rendered
    assert f"Environment=ACCOUNTS_CONFIG_FILE={install_dir}/state/credentials.json" in rendered
    assert "Environment=ACCOUNTS_STATE_FILE=" in rendered
    assert f"Environment=ACCOUNTS_STATE_FILE={install_dir}/state/state.json" in rendered

    # [Install] WantedBy=default.target is present so a user who *manually*
    # runs `systemctl --user enable` gets the desired behavior, but the
    # installer never invokes `enable` (enforced in T-2.4).
    assert "[Install]" in rendered
    assert "WantedBy=default.target" in rendered


def test_unit_does_not_contain_enable_invocations(tmp_path: Path) -> None:
    """
    The unit file itself MUST NOT contain `enable` or `WantedBy=multi-user`
    (which is the system-wide target; we want per-user only).
    """
    rendered = render_unit(tmp_path / "x", tmp_path)
    assert "systemctl " not in rendered  # template has no commands, only keys
    assert "multi-user.target" not in rendered
