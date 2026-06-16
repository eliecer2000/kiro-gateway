# -*- coding: utf-8 -*-

"""Release assets and checksum verification must form one coherent contract."""

from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path

from tests.unit.install_script.conftest import REPO_ROOT


def test_installer_uses_canonical_release_asset() -> None:
    common = (REPO_ROOT / "scripts" / "lib" / "install-common.sh").read_text()
    installer = (REPO_ROOT / "scripts" / "install.sh").read_text()

    assert "jwadow/kiro-gateway" in common
    assert "jwadow/kiro-gateway" in installer
    assert "eliecer2000/kiro-gateway" not in common
    assert "eliecer2000/kiro-gateway" not in installer
    assert "kiro-gateway-${VERSION}.tar.gz" in common
    assert "releases/download/v${VERSION}" in common


def test_release_workflow_publishes_tarball_and_checksums() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "release.yml").read_text()
    build_script = (REPO_ROOT / "scripts" / "build-release.sh").read_text()

    assert "scripts/build-release.sh" in workflow
    assert "SHA256SUMS" in workflow
    assert "kiro-gateway-*.tar.gz" in workflow
    assert "sha256sum" in build_script
    assert "shasum -a 256" in build_script


def test_installer_has_portable_checksum_fallback() -> None:
    common = (REPO_ROOT / "scripts" / "lib" / "install-common.sh").read_text()

    assert "command -v sha256sum" in common
    assert "command -v shasum" in common
    assert "shasum -a 256" in common


def test_sha256_file_works_when_only_shasum_is_available(tmp_path: Path) -> None:
    """macOS verification must not depend on GNU sha256sum."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    shasum = bin_dir / "shasum"
    shasum.write_text(
        textwrap.dedent(
            """\
            #!/bin/bash
            printf 'abc123  %s\\n' "$3"
            """
        )
    )
    shasum.chmod(0o755)
    awk = bin_dir / "awk"
    awk.write_text("#!/bin/bash\nread -r first rest\nprintf '%s\\n' \"$first\"\n")
    awk.chmod(0o755)
    target = tmp_path / "archive.tar.gz"
    target.write_text("payload")
    common = REPO_ROOT / "scripts" / "lib" / "install-common.sh"
    env = os.environ.copy()
    env["PATH"] = str(bin_dir)

    result = subprocess.run(
        ["/bin/bash", "-c", f'source "{common}"; sha256_file "{target}"'],
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "abc123"
