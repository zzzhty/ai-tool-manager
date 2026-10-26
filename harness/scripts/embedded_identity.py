"""Identity of the complete shipped engine, owned by ATM materialization.

Plugin generations retain their existing narrower contract. This identity is
checked at distribution/write boundaries, never by recorded status reads.
"""
from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

ALGORITHM = "atm-engine-content-v1"
MARKER_NAME = ".atm-embedded.json"


def ignored(name: str) -> bool:
    return name in {".git", "__pycache__", ".venv", MARKER_NAME} or name.endswith((".pyc", ".pyo"))


def ordinary(path: Path, *, directory: bool) -> bool:
    try:
        metadata = path.lstat()
    except OSError:
        return False
    expected = stat.S_ISDIR if directory else stat.S_ISREG
    return expected(metadata.st_mode) and not (
        getattr(metadata, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def content_identity(root: Path) -> str:
    if not ordinary(root, directory=True):
        raise SystemExit("embedded engine root must be an ordinary directory")
    def unreadable_directory(error: OSError) -> None:
        raise SystemExit(f"cannot inspect embedded engine directory: {error.filename}") from error

    digest = hashlib.sha256(ALGORITHM.encode() + b"\0")
    for parent, directories, files in os.walk(root, followlinks=False, onerror=unreadable_directory):
        directories[:] = sorted(name for name in directories if not ignored(name))
        for name in directories:
            if not ordinary(Path(parent) / name, directory=True):
                raise SystemExit("embedded engine must not contain directory links")
        for name in sorted(files):
            if ignored(name):
                continue
            path = Path(parent) / name
            if not ordinary(path, directory=False):
                raise SystemExit("embedded engine must contain only regular files")
            relative = path.relative_to(root).as_posix().encode("utf-8")
            data = path.read_bytes()
            digest.update(len(relative).to_bytes(8, "big") + relative)
            digest.update(len(data).to_bytes(8, "big") + data)
    return "sha256:" + digest.hexdigest()
