# -*- coding: utf-8 -*-

"""launchd failures must be visible and must never trigger direct startup."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

WRAPPER = Path(__file__).resolve().parents[4] / "scripts" / "kiro-gateway"


def test_launchd_start_failure_is_actionable(tmp_path: Path, installed_env: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    launchctl = bin_dir / "launchctl"
    launchctl.write_text("#!/usr/bin/env bash\nexit 1\n")
    launchctl.chmod(0o755)
    marker = installed_env / "state" / "direct-started"
    (installed_env / "venv" / "bin").mkdir(parents=True, exist_ok=True)
    fake_python = installed_env / "venv" / "bin" / "python"
    fake_python.write_text(f'#!/usr/bin/env bash\ntouch "{marker}"\n')
    fake_python.chmod(0o755)

    home = tmp_path / "home"
    plist_dir = home / "Library" / "LaunchAgents"
    plist_dir.mkdir(parents=True)
    (plist_dir / "com.jwadow.kiro-gateway.plist").write_text("<plist/>\n")
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home),
            "KIRO_INSTALL_DIR": str(installed_env),
            "PATH": f"{bin_dir}:{env.get('PATH', '')}",
            "UNAME_S": "Darwin",
        }
    )

    result = subprocess.run(
        ["bash", str(WRAPPER), "start"], env=env, capture_output=True, text=True
    )

    assert result.returncode != 0
    assert "launchctl" in result.stderr
    assert not marker.exists()
