"""Unicode-safe image I/O built on OpenCV encoders/decoders."""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np


def imread(path: str | Path, flags: int = cv2.IMREAD_COLOR) -> np.ndarray | None:
    path = Path(path)
    try:
        data = np.fromfile(str(path), dtype=np.uint8)
    except OSError:
        return None
    if data.size == 0:
        return None
    return cv2.imdecode(data, flags)


def imwrite(path: str | Path, image: np.ndarray, quality: int | None = None) -> bool:
    """Write an image, handling non-ASCII Windows paths and JPEG quality."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    suffix = path.suffix.lower() or ".png"
    params: list[int] = []
    if suffix in (".jpg", ".jpeg") and quality is not None:
        params = [cv2.IMWRITE_JPEG_QUALITY, int(quality)]
    try:
        ok, encoded = cv2.imencode(suffix, image, params)
        if not ok:
            return False
        encoded.tofile(str(path))
        return True
    except (cv2.error, OSError, ValueError):
        return False


def save_thumbnail(source: np.ndarray, path: str | Path, width: int = 360, quality: int = 88) -> bool:
    if source is None or source.size == 0:
        return False
    h, w = source.shape[:2]
    if w <= 0 or h <= 0:
        return False
    if w > width:
        new_h = max(1, int(round(h * width / w)))
        thumb = cv2.resize(source, (int(width), new_h), interpolation=cv2.INTER_AREA)
    else:
        thumb = source
    return imwrite(path, thumb, quality=quality)


def image_size(path: str | Path) -> tuple[int, int] | None:
    image = imread(path, cv2.IMREAD_UNCHANGED)
    if image is None:
        return None
    h, w = image.shape[:2]
    return int(w), int(h)
