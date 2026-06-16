# -*- coding: utf-8 -*-

"""End-to-end verified installation using release-shaped local assets."""

from __future__ import annotations

import os
import subprocess

from tests.unit.install_script.conftest import REPO_ROOT


def test_secure_install_verifies_published_release_assets(tmp_path, stub_curl) -> None:
    install_dir = tmp_path / "install"
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(tmp_path),
            "UNAME_S": "Darwin",
            "PATH": f"{stub_curl['bin_dir']}:{env.get('PATH', '')}",
            "STUB_TARBALL_PATH": str(stub_curl["tarball_path"]),
            "STUB_SERVE_SHA256SUMS": "1",
        }
    )

    result = subprocess.run(
        [
            "bash",
            str(REPO_ROOT / "scripts" / "install.sh"),
            "--install-dir",
            str(install_dir),
            "--version",
            "2.5.0",
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr
    assert (install_dir / "app" / "VERSION").read_text().strip() == "2.5.0"
    calls = stub_curl["calls_log"].read_text()
    assert "/releases/download/v2.5.0/kiro-gateway-2.5.0.tar.gz" in calls
    assert "/releases/download/v2.5.0/SHA256SUMS" in calls
