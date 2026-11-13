# =====================================================================
# INTENTIONALLY VULNERABLE CODE - LAB / SANDBOX USE ONLY.
# CM-0002 / CWE-22: read_note() joins user input to the notes directory
# without normalizing or checking the result.
# Reference fix: patches/CM-0002-path-traversal.diff
# =====================================================================
"""Topic notes (short markdown files shown next to a topic)."""
from __future__ import annotations

import os
from typing import Optional

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NOTES_DIR = os.path.join(BASE_DIR, "data", "notes")


class NoteNotFound(Exception):
    """Raised when a note does not exist (or is not allowed)."""


def read_note(name: str, notes_dir: Optional[str] = None) -> str:
    """Return the text of a note file from the notes directory."""
    base = notes_dir or NOTES_DIR
    # VULNERABLE (CWE-22): "../" sequences in name escape the notes dir.
    path = os.path.join(base, name)
    if not os.path.isfile(path):
        raise NoteNotFound(name)
    with open(path, encoding="utf-8") as handle:
        return handle.read()
