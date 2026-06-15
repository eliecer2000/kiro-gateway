# -*- coding: utf-8 -*-

"""
T-2.3 — Service load uses `launchctl bootstrap`, NEVER `launchctl load -w`.

Spec: service-management §"Scenario: Plist is loaded with launchctl bootstrap
(not load -w)".
Static gate: `rg 'load -w' scripts/install.sh scripts/kiro-gateway
scripts/lib/install-common.sh` MUST return zero matches.
Tasks: T-2.3 [red] → T-2.3 [green] → T-2.3 [refactor]
"""

from __future__ import annotations

import re
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


def test_no_load_w_in_scripts() -> None:
    """
    Static gate: `load -w` MUST NOT appear in any of the install scripts.
    This is the `launchctl load -w` (deprecated) command that silently flips
    RunAtLoad=true — explicitly forbidden by spec.
    """
    pattern = re.compile(r"\bload\s+-w\b")
    for path in _scripts_files():
        if not path.exists():
            continue
        text = path.read_text()
        for line_num, line in enumerate(text.splitlines(), 1):
            # Skip pure comment lines and heredoc example text.
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            assert not pattern.search(line), (
                f"{path}:{line_num}: forbidden 'load -w' substring in {line!r}"
            )


def test_no_load_w_in_rg_search() -> None:
    """
    Run `rg 'load -w' scripts/install.sh scripts/lib/install-common.sh`
    and assert the output is empty.
    """
    rg = _find_rg()
    cmd = [rg, "load -w", "scripts/install.sh", "scripts/lib/install-common.sh"]
    result = subprocess.run(
        cmd, cwd=str(REPO_ROOT), capture_output=True, text=True
    )
    assert result.stdout.strip() == "", (
        f"rg 'load -w' found forbidden matches:\n{result.stdout}"
    )
    # rg returns 1 when no matches; that's the success case for us.


def test_load_uses_bootstrap_in_lib() -> None:
    """
    The shared library MUST call `launchctl bootstrap` (not load/unload).
    Implementation of `load_service` lands in T-2.11; this test just
    asserts the substring is present somewhere in the lib.
    """
    text = INSTALL_COMMON_SH.read_text()
    assert "launchctl bootstrap" in text, (
        "expected 'launchctl bootstrap' in install-common.sh"
    )


def _find_rg() -> str:
    import shutil

    rg = shutil.which("rg")
    if rg is None:
        pytest.skip("rg not on PATH")
    return rg
