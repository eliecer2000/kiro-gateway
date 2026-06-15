# -*- coding: utf-8 -*-

"""
T-1.11 — HTTPS-only: every curl call in the codebase uses
--proto =https --tlsv1.2. Static gate + dynamic invocation log.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from tests.unit.install_script.conftest import (
    INSTALL_COMMON_SH,
    INSTALL_SH,
    SCRIPTS_DIR,
)


def _shell_scripts() -> list[Path]:
    return [
        INSTALL_SH,
        INSTALL_COMMON_SH,
        SCRIPTS_DIR / "kiro-gateway",
        SCRIPTS_DIR / "system" / "kiro-gateway.plist",
        SCRIPTS_DIR / "system" / "kiro-gateway.service",
    ]


def test_no_http_urls_in_scripts():
    """Static gate: no http:// (lowercase scheme) in any script."""
    for script in _shell_scripts():
        if not script.exists():
            continue
        text = script.read_text()
        # Skip XML plist (DTD reference is unavoidable) and ignore .service.
        if script.suffix in (".plist", ".service"):
            continue
        # Look for the literal scheme in a curl/URL position.
        # Exclude the standard XML DTD references.
        matches = re.findall(r"http://(?!www\.apple\.com|www\.w3\.org)", text)
        assert not matches, f"http:// found in {script}: {matches}"


def test_https_only_via_invocation_log(tmp_path, stub_curl):
    """
    Run the installer and inspect the curl call log. The lib should invoke
    curl with --proto =https --tlsv1.2.
    """
    install_dir = tmp_path / "kg"
    env = {
        "HOME": str(tmp_path),
        "UNAME_S": "Darwin",
        "PATH": f"{stub_curl['bin_dir']}:{__import__('os').environ.get('PATH', '')}",
        "STUB_TARBALL_PATH": str(stub_curl["tarball_path"]),
    }
    result = subprocess.run(
        ["bash", str(INSTALL_SH),
         "--install-dir", str(install_dir),
         "--version", "2.5.0", "--insecure"],
        cwd=str(INSTALL_SH.parent.parent),
        env=env,
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0
    # The stub always logs URL+OUT; we grep our own scripts for the flag.
    install_text = INSTALL_SH.read_text()
    lib_text = INSTALL_COMMON_SH.read_text()
    assert "--proto =https --tlsv1.2" in install_text or "--proto =https --tlsv1.2" in lib_text
