"""Media metadata shared by every lesson-preparation stage."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class VideoInfo:
    """Metadata for one source video."""

    path: str = ""
    width: int = 0
    height: int = 0
    fps: float = 0.0
    duration_sec: float = 0.0
    frame_count: int = 0
    codec: str = ""
    rotation: int = 0
    has_audio: bool = False
    file_size: int = 0

    @property
    def resolution(self) -> str:
        return f"{self.width} × {self.height}" if self.width and self.height else "未知"

    @property
    def aspect(self) -> float:
        return self.width / self.height if self.width and self.height else 16 / 9

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "width": int(self.width),
            "height": int(self.height),
            "fps": round(float(self.fps), 4),
            "duration_sec": round(float(self.duration_sec), 3),
            "frame_count": int(self.frame_count),
            "codec": self.codec,
            "rotation": int(self.rotation),
            "has_audio": bool(self.has_audio),
            "file_size": int(self.file_size),
        }

    @classmethod
    def from_dict(cls, data: dict | None) -> "VideoInfo":
        data = data or {}
        return cls(
            path=str(data.get("path") or ""),
            width=int(data.get("width") or 0),
            height=int(data.get("height") or 0),
            fps=float(data.get("fps") or 0.0),
            duration_sec=float(data.get("duration_sec") or 0.0),
            frame_count=int(data.get("frame_count") or 0),
            codec=str(data.get("codec") or ""),
            rotation=int(data.get("rotation") or 0),
            has_audio=bool(data.get("has_audio")),
            file_size=int(data.get("file_size") or 0),
        )
