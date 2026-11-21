"""Project file naming and asset-path conventions shared by all stages.

A stage project consists of one JSON file and a sibling ``*_assets`` folder.
All asset paths stored inside the JSON are relative to that folder, so the
pair can be moved together without breaking.

The helper functions take the stage's project suffixes as arguments; ``core``
does not assume any particular stage's file naming.
"""
from __future__ import annotations

import os
from pathlib import Path


def base_name(
    project_path: str | Path,
    suffixes: tuple[str, ...] = (".json",),
) -> str:
    """Return the project name with the longest matching suffix removed."""
    name = Path(project_path).name
    lower = name.lower()
    for suffix in sorted(suffixes, key=len, reverse=True):
        if lower.endswith(suffix.lower()):
            return name[: -len(suffix)]
    return Path(project_path).stem


def assets_dir_for_project(
    project_path: str | Path,
    suffixes: tuple[str, ...] = (".json",),
) -> Path:
    path = Path(project_path)
    return path.with_name(base_name(path, suffixes) + "_assets")


def suggested_project_path(
    video_path: str | Path,
    suffix: str = ".json",
) -> Path:
    video = Path(video_path)
    return video.with_name(video.stem + suffix)


def prepare_project_path(
    project_path: str | Path,
    suffix: str = ".json",
    known_suffixes: tuple[str, ...] | None = None,
) -> tuple[Path, Path]:
    path = Path(project_path)
    if path.suffix.lower() != ".json":
        path = path.with_name(path.name + suffix)
    suffixes = known_suffixes or tuple(dict.fromkeys((suffix, ".json")))
    path.parent.mkdir(parents=True, exist_ok=True)
    assets = assets_dir_for_project(path, suffixes)
    assets.mkdir(parents=True, exist_ok=True)
    return path, assets


def resolve_asset(project, relative_path: str) -> Path | None:
    """Resolve an asset path stored relative to the project's assets folder."""
    if not relative_path:
        return None
    root = getattr(project, "assets_root", None)
    if not root:
        return None
    return Path(root) / relative_path.replace("/", os.sep)
