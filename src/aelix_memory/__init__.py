"""Aelix Memory. Importing the SDK performs no I/O and needs no host installation."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aelix_coding_agent.extensions.api import ExtensionAPI

__version__ = "0.1.0"


def setup(aelix: ExtensionAPI) -> None:
    """The host's official extension entry point; imports are deliberately lazy."""
    from .extension import register

    register(aelix)
