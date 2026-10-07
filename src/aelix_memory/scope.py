"""Project identity comes from a host cwd, never from model-provided tool arguments."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Scope:
    id: str
    root: Path

    @classmethod
    def for_project(cls, cwd: str | Path) -> Scope:
        root = Path(cwd).expanduser().resolve(strict=True)
        if not root.is_dir():
            raise ValueError("Project must be an existing directory.")
        for directory in (root, *root.parents):
            if (directory / ".git").exists():
                root = directory
                break
        return cls(hashlib.sha256(os.fsencode(root)).hexdigest()[:24], root)


def memory_home() -> Path:
    override = os.environ.get("AELIX_MEMORY_HOME")
    return Path(override).expanduser().absolute() if override else Path.home() / ".aelix" / "memory"
