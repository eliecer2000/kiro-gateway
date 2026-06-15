# -*- coding: utf-8 -*-

"""
T-4.2: docs/install.md mentions the logrotate snippet for v1 users.

The sample is a copy-paste config for the user's
~/.config/logrotate.d/kiro-gateway file.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
DOCS = REPO_ROOT / "docs" / "install.md"


def test_docs_install_mentions_logrotate():
    """
    GIVEN the user-facing docs at docs/install.md
    WHEN the file is read
    THEN it contains a logrotate sample that references the install's
    logs/ directory and the standard logrotate.d path.
    """
    text = DOCS.read_text()
    assert "logrotate" in text, "expected 'logrotate' in docs/install.md"
    # The sample should reference the install's logs/ path.
    assert "kiro-gateway.log" in text or "${INSTALL_DIR}/logs" in text, (
        "expected logrotate sample to reference kiro-gateway.log or ${INSTALL_DIR}/logs"
    )
