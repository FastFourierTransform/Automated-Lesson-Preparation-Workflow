"""Generic coordinate conversion helpers.

Regions are always stored as normalized coordinates relative to the decoded
video frame (0..1).  This keeps selections stable regardless of preview size
and allows exports at the original resolution.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class Rect:
    """A normalized rectangle (x, y, width, height) in the range 0..1."""

    x: float
    y: float
    w: float
    h: float

    @classmethod
    def full_frame(cls) -> "Rect":
        return cls(0.0, 0.0, 1.0, 1.0)

    @classmethod
    def from_ltrb(cls, left: float, top: float, right: float, bottom: float) -> "Rect":
        return cls(left, top, max(0.0, right - left), max(0.0, bottom - top)).clamped()

    def clamped(self) -> "Rect":
        x = min(max(float(self.x), 0.0), 1.0)
        y = min(max(float(self.y), 0.0), 1.0)
        w = min(max(float(self.w), 0.0), 1.0 - x)
        h = min(max(float(self.h), 0.0), 1.0 - y)
        return Rect(x, y, w, h)

    @property
    def left(self) -> float:
        return self.x

    @property
    def top(self) -> float:
        return self.y

    @property
    def right(self) -> float:
        return self.x + self.w

    @property
    def bottom(self) -> float:
        return self.y + self.h

    @property
    def area(self) -> float:
        return max(0.0, self.w) * max(0.0, self.h)

    def is_valid(self, min_area: float = 0.0005) -> bool:
        return self.w > 0.002 and self.h > 0.002 and self.area >= min_area

    def contains(self, other: "Rect") -> bool:
        return (
            other.left >= self.left - 1e-9
            and other.top >= self.top - 1e-9
            and other.right <= self.right + 1e-9
            and other.bottom <= self.bottom + 1e-9
        )

    def intersect(self, other: "Rect") -> "Rect | None":
        left = max(self.left, other.left)
        top = max(self.top, other.top)
        right = min(self.right, other.right)
        bottom = min(self.bottom, other.bottom)
        if right <= left or bottom <= top:
            return None
        return Rect.from_ltrb(left, top, right, bottom)

    def to_pixels(self, frame_width: int, frame_height: int) -> tuple[int, int, int, int]:
        """Return integer (x, y, w, h), guaranteed to be inside the frame."""
        left = int(round(self.clamped().left * frame_width))
        top = int(round(self.clamped().top * frame_height))
        right = int(round(self.clamped().right * frame_width))
        bottom = int(round(self.clamped().bottom * frame_height))
        left = max(0, min(left, frame_width - 1))
        top = max(0, min(top, frame_height - 1))
        right = max(left + 1, min(right, frame_width))
        bottom = max(top + 1, min(bottom, frame_height))
        return left, top, right - left, bottom - top

    def to_dict(self) -> dict:
        return {"x": round(self.x, 6), "y": round(self.y, 6), "w": round(self.w, 6), "h": round(self.h, 6)}

    @classmethod
    def from_dict(cls, data: dict | None, default: "Rect | None" = None) -> "Rect | None":
        if not data:
            return default
        try:
            return cls(float(data["x"]), float(data["y"]), float(data["w"]), float(data["h"])).clamped()
        except (KeyError, TypeError, ValueError):
            return default

    def format(self) -> str:
        return f"x={self.x:.3f}, y={self.y:.3f}, w={self.w:.3f}, h={self.h:.3f}"


def crop_rect(image: np.ndarray, rect: Rect) -> np.ndarray:
    """Crop a normalized region from a BGR/gray image."""
    h, w = image.shape[:2]
    x, y, cw, ch = rect.to_pixels(w, h)
    return image[y : y + ch, x : x + cw].copy()


def crop_relative(image: np.ndarray, rect: Rect) -> np.ndarray:
    """Crop a region whose coordinates are relative to an already cropped frame."""
    return crop_rect(image, rect)


def relative_rect(inner: Rect, outer: Rect) -> Rect | None:
    """Express ``inner`` in coordinates relative to ``outer``.

    Returns None when there is no overlap.  The result may extend outside
    [0, 1] only if an invalid outer rectangle is supplied; inputs are clamped.
    """
    intersected = inner.intersect(outer)
    if intersected is None or outer.w <= 0 or outer.h <= 0:
        return None
    return Rect(
        (intersected.left - outer.left) / outer.w,
        (intersected.top - outer.top) / outer.h,
        intersected.w / outer.w,
        intersected.h / outer.h,
    ).clamped()


def mask_region(image: np.ndarray, rect: Rect | None, color: int | tuple = 0) -> np.ndarray:
    """Return a copy with a normalized rectangle filled with a solid color."""
    result = image.copy()
    if rect is None or not rect.is_valid():
        return result
    h, w = result.shape[:2]
    x, y, cw, ch = rect.to_pixels(w, h)
    result[y : y + ch, x : x + cw] = color
    return result


def fit_rect(
    image_width: int,
    image_height: int,
    area_width: float,
    area_height: float,
) -> tuple[float, float, float, float]:
    """Fit an image into an area without distortion, centered.

    Returns (left, top, width, height) in the same units as the area.
    """
    if image_width <= 0 or image_height <= 0 or area_width <= 0 or area_height <= 0:
        return 0.0, 0.0, 0.0, 0.0
    scale = min(area_width / image_width, area_height / image_height)
    w = image_width * scale
    h = image_height * scale
    return (area_width - w) / 2.0, (area_height - h) / 2.0, w, h


def bgr_to_qimage(frame: np.ndarray):
    """Convert a BGR numpy frame to a detached QImage (requires PySide6)."""
    from PySide6.QtGui import QImage

    if frame is None:
        return QImage()
    if frame.ndim == 2:
        rgb = cv2.cvtColor(frame, cv2.COLOR_GRAY2RGB)
    else:
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    h, w, channels = rgb.shape
    return QImage(rgb.data, w, h, channels * w, QImage.Format.Format_RGB888).copy()
