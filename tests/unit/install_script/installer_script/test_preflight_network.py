# -*- coding: utf-8 -*-

"""
T-1.6 — preflight_network exits 1 with the exact spec message when
github.com is unreachable.
"""

from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path

import pytest

from tests.unit.install_script.conftest import REPO_ROOT


def test_preflight_no_network_fails(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    # Stub curl that returns 000 for the network probe.
    (bin_dir / "curl").write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env bash
            # Pretend github.com is unreachable.
            if [[ "$*" == *"-w"* ]]; then
              printf '000'
            fi
            exit 0
            """
        )
    )
    (bin_dir / "curl").chmod(0o755)
    (bin_dir / "python3").write_text(
        "#!/usr/bin/env bash\n[[ $1 == -V || $1 == --version ]] && echo Python 3.12.0\nexit 0\n"
    )
    (bin_dir / "python3").chmod(0o755)
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
    expected = "Cannot reach github.com. Check your connection."
    assert expected in result.stderr, f"missing exact message. stderr:\n{result.stderr}"
