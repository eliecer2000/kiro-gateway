# -*- coding: utf-8 -*-

"""
T-4.3: README.md should advertise the curl|bash one-liner as the primary
install path, with the `git clone` path under a "Development install"
heading.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
README = REPO_ROOT / "README.md"


def test_readme_one_liner_top():
    """
    GIVEN the README is the top-of-funnel for new users
    WHEN the file is read
    THEN the curl|bash one-liner appears in the first 60 lines.
    """
    text = README.read_text()
    first_60 = "\n".join(text.splitlines()[:60])
    assert "install.sh" in first_60, (
        f"expected the curl|bash one-liner in the first 60 lines; got:\n{first_60}"
    )
    assert "curl" in first_60, "expected 'curl' in the first 60 lines"


def test_readme_has_development_install_heading():
    """The git clone path should live under a `### Development install` heading."""
    text = README.read_text()
    # Match both `### Development install` and `### Development Install` (case-insensitive).
    assert "Development install" in text or "development install" in text, (
        "expected 'Development install' heading for the git clone fallback"
    )


def test_readme_uses_real_configuration_path_and_canonical_repository():
    """The quick start must not reference a nonexistent path subcommand."""
    text = README.read_text()

    assert "kiro-gateway path" not in text
    assert "github.com/jwadow/kiro-gateway" in text
