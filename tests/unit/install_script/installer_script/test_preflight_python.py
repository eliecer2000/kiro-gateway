# -*- coding: utf-8 -*-

"""
T-1.5 — preflight_python exits non-zero with the exact spec message
when python3 reports 3.9.x.
"""

from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path

import pytest

from tests.unit.install_script.conftest import REPO_ROOT


def _make_python39_stub(bin_dir: Path) -> Path:
    py = bin_dir / "python3"
    py.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env bash
            if [[ "$1" == "-V" ]] || [[ "$1" == "--version" ]]; then
              echo "Python 3.9.18"
              exit 0
            fi
            exit 0
            """
        )
    )
    py.chmod(0o755)
    return py


def test_preflight_python_39_fails(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _make_python39_stub(bin_dir)
    # Need stub curl + stub sha256sum on PATH too.
    (bin_dir / "curl").write_text("#!/usr/bin/env bash\nexit 0\n")
    (bin_dir / "curl").chmod(0o755)
    (bin_dir / "tar").write_text("#!/usr/bin/env bash\nexit 0\n")
    (bin_dir / "tar").chmod(0o755)
    (bin_dir / "sha256sum").write_text("#!/usr/bin/env bash\nexit 0\n")
    (bin_dir / "sha256sum").chmod(0o755)

    env = {
        "HOME": str(tmp_path),
        "UNAME_S": "Darwin",
        "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
    }
    result = subprocess.run(
        ["bash", str(REPO_ROOT / "scripts" / "install.sh"),
         "--install-dir", str(tmp_path / "kg")],
        cwd=str(REPO_ROOT), env=env,
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode != 0, f"installer unexpectedly succeeded: {result.stdout}"
    expected = "Python 3.10 or newer is required. Found 3.9.x. Install via pyenv or your package manager."
    assert expected in result.stderr, f"missing exact message. stderr:\n{result.stderr}"
