"""Stage contract and registry types.

A *stage* is one independent step in the lesson-preparation workflow, such as
``video_to_slides`` or a future ``video_to_handout``.  The core package owns
media decoding, geometry, project conventions and shared UI widgets; each stage
owns its own models, analysis/export logic and window.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal

StageStatus = Literal["available", "planned"]


@dataclass(frozen=True)
class StageInfo:
    """Human-readable metadata used by the launcher and documentation."""

    id: str
    name: str
    summary: str
    inputs: str
    outputs: str
    status: StageStatus = "available"
    order: int = 0


@dataclass(frozen=True)
class Stage:
    """A stage implementation plus its entry points.

    ``create_window`` and ``open_path`` are intentionally optional so planned
    stages can be registered before they have a UI.
    """

    info: StageInfo
    create_window: Callable[[], Any] | None = None
    open_path: Callable[[Any, Path], bool] | None = None
    file_suffixes: tuple[str, ...] = ()

    @property
    def available(self) -> bool:
        return self.info.status == "available" and self.create_window is not None
