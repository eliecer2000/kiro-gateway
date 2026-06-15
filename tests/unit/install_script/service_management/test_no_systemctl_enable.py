# -*- coding: utf-8 -*-

"""
T-2.4 — Installer MUST NOT call `systemctl --user enable` (or any
`systemctl ... enable ...` variant).

Spec: service-management §"Scenario: daemon-reload runs but enable does not".
Static gate: `rg 'systemctl .* enable' scripts/install.sh scripts/kiro-gateway
scripts/lib/install-common.sh` MUST return zero matches.
Tasks: T-2.4 [red] → T-2.4 [green] → T-2.4 [refactor]
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.unit.install_script.conftest import (
    INSTALL_COMMON_SH,
    INSTALL_SH,
    REPO_ROOT,
)


def _scripts_files() -> list[Path]:
    return [INSTALL_SH, INSTALL_COMMON_SH]


def test_no_systemctl_enable_in_scripts() -> None:
    """
    Static gate: `systemctl .* enable` MUST NOT appear in any install
    script (outside of comments). The service is intentionally never
    autostarted at install time; users may `enable` manually.
    """
    pattern = re.compile(r"\bsystemctl\b[^#\n]*\benable\b")
    for path in _scripts_files():
        if not path.exists():
            continue
        text = path.read_text()
        for line_num, line in enumerate(text.splitlines(), 1):
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            assert not pattern.search(line), (
                f"{path}:{line_num}: forbidden 'systemctl ... enable' in {line!r}"
            )


def test_no_systemctl_enable_in_rg_search() -> None:
    """Run rg and assert empty output."""
    rg = shutil.which("rg")
    if rg is None:
        pytest.skip("rg not on PATH")
    cmd = [rg, "systemctl .* enable", "scripts/install.sh", "scripts/lib/install-common.sh"]
    result = subprocess.run(
        cmd, cwd=str(REPO_ROOT), capture_output=True, text=True
    )
    assert result.stdout.strip() == "", (
        f"rg 'systemctl .* enable' found forbidden matches:\n{result.stdout}"
    )


def test_daemon_reload_present() -> None:
    """
    The lib MUST use `systemctl --user daemon-reload` (the only allowed
    enable-adjacent command).
    """
    text = INSTALL_COMMON_SH.read_text()
    assert "systemctl --user daemon-reload" in text
