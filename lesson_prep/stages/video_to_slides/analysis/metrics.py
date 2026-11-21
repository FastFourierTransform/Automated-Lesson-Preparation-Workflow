"""Image comparison and frame quality metrics used by the analysis engine."""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from ....core.geometry import Rect, crop_rect, relative_rect
from ..models import AnalysisSettings


@dataclass
class FrameDiff:
    changed_ratio: float = 0.0
    mad: float = 0.0
    ssim: float = 1.0
    changed_bbox_ratio: float = 0.0
    largest_component_ratio: float = 0.0

    def is_coarse_change(self, settings: AnalysisSettings) -> bool:
        return (
            self.changed_ratio >= settings.coarse_change_ratio_threshold
            or self.mad >= settings.coarse_mad_threshold
            or self.ssim <= settings.coarse_ssim_threshold
        )

    def is_stable(self, settings: AnalysisSettings) -> bool:
        return (
            self.changed_ratio <= settings.stable_change_ratio_threshold
            and self.mad <= settings.stable_mad_threshold
            and self.ssim >= settings.stable_ssim_threshold
        )

    def as_dict(self) -> dict[str, float]:
        return {
            "changed_ratio": round(self.changed_ratio, 5),
            "mad": round(self.mad, 4),
            "ssim": round(self.ssim, 5),
            "changed_bbox_ratio": round(self.changed_bbox_ratio, 5),
            "largest_component_ratio": round(self.largest_component_ratio, 5),
        }


@dataclass
class PreparedFrame:
    gray: np.ndarray
    color: np.ndarray | None
    mask: np.ndarray
    quality: dict[str, float]


def _resize_to_width(image: np.ndarray, width: int) -> np.ndarray:
    h, w = image.shape[:2]
    if w <= 0 or h <= 0:
        raise ValueError("空图像")
    target_w = min(int(width), w)
    target_h = max(1, int(round(h * target_w / w)))
    if target_w == w:
        return image
    return cv2.resize(image, (target_w, target_h), interpolation=cv2.INTER_AREA)


def make_valid_mask(shape: tuple[int, int], camera_regions_local: list[Rect] | None) -> np.ndarray:
    h, w = shape
    mask = np.full((h, w), 255, dtype=np.uint8)
    for camera_region_local in camera_regions_local or []:
        if camera_region_local is None or not camera_region_local.is_valid():
            continue
        x, y, cw, ch = camera_region_local.to_pixels(w, h)
        mask[y : y + ch, x : x + cw] = 0
    return mask


def prepare_frame(
    frame: np.ndarray,
    ppt_region: Rect,
    camera_regions: list[Rect] | Rect | None,
    analysis_width: int,
    want_color: bool = False,
) -> PreparedFrame:
    """Crop the PPT area, exclude all camera regions, and downscale."""
    if isinstance(camera_regions, Rect):
        camera_regions = [camera_regions]
    camera_regions = [
        camera
        for camera in (camera_regions or [])
        if camera is not None and camera.is_valid()
    ]
    crop = crop_rect(frame, ppt_region)
    if crop.size == 0:
        raise ValueError("PPT 区域为空")
    cameras_local = [
        local
        for local in (relative_rect(camera, ppt_region) for camera in camera_regions)
        if local is not None
    ]
    # Size the mask from the original crop, then resize it together with the
    # grayscale image so the exclusion stays aligned.
    original_mask = make_valid_mask(crop.shape[:2], cameras_local)
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    gray_small = _resize_to_width(gray, analysis_width)
    mask_small = _resize_to_width(original_mask, analysis_width)
    _, mask_small = cv2.threshold(mask_small, 127, 255, cv2.THRESH_BINARY)
    color_small = None
    if want_color:
        color = crop
        if cameras_local:
            h, w = color.shape[:2]
            color = color.copy()
            for camera_local in cameras_local:
                x, y, cw, ch = camera_local.to_pixels(w, h)
                color[y : y + ch, x : x + cw] = 0
        color_small = _resize_to_width(color, analysis_width)
    return PreparedFrame(
        gray=gray_small,
        color=color_small,
        mask=mask_small,
        quality=evaluate_frame_quality(gray_small, crop.shape[:2]),
    )


def _masked_mean(values: np.ndarray, mask: np.ndarray) -> float:
    valid = int(np.count_nonzero(mask))
    if valid <= 0:
        return float(values.mean()) if values.size else 0.0
    return float(values[mask > 0].mean())


def compute_ssim(image_a: np.ndarray, image_b: np.ndarray, mask: np.ndarray | None = None) -> float:
    """Gaussian-window SSIM for uint8 grayscale images of the same shape."""
    if image_a.shape != image_b.shape:
        image_b = cv2.resize(image_b, (image_a.shape[1], image_a.shape[0]), interpolation=cv2.INTER_AREA)
    a = image_a.astype(np.float32)
    b = image_b.astype(np.float32)
    if mask is not None and mask.shape != a.shape:
        mask = cv2.resize(mask, (a.shape[1], a.shape[0]), interpolation=cv2.INTER_NEAREST)
    if mask is not None:
        # Invalid pixels are made identical so that they cannot lower the
        # structural score. The mean is masked as well.
        b = b.copy()
        b[mask == 0] = a[mask == 0]
    c1 = (0.01 * 255) ** 2
    c2 = (0.03 * 255) ** 2
    kernel = (11, 11)
    sigma = 1.5
    mu_a = cv2.GaussianBlur(a, kernel, sigma)
    mu_b = cv2.GaussianBlur(b, kernel, sigma)
    mu_a2 = mu_a * mu_a
    mu_b2 = mu_b * mu_b
    mu_ab = mu_a * mu_b
    sigma_a2 = cv2.GaussianBlur(a * a, kernel, sigma) - mu_a2
    sigma_b2 = cv2.GaussianBlur(b * b, kernel, sigma) - mu_b2
    sigma_ab = cv2.GaussianBlur(a * b, kernel, sigma) - mu_ab
    ssim_map = ((2 * mu_ab + c1) * (2 * sigma_ab + c2)) / (
        (mu_a2 + mu_b2 + c1) * (sigma_a2 + sigma_b2 + c2) + 1e-9
    )
    return float(np.clip(_masked_mean(ssim_map, mask) if mask is not None else ssim_map.mean(), -1.0, 1.0))


def compare_frames(previous: np.ndarray, current: np.ndarray, mask: np.ndarray, pixel_threshold: int) -> FrameDiff:
    if previous.shape != current.shape:
        current = cv2.resize(current, (previous.shape[1], previous.shape[0]), interpolation=cv2.INTER_AREA)
        mask = cv2.resize(mask, (previous.shape[1], previous.shape[0]), interpolation=cv2.INTER_NEAREST)
    difference = cv2.absdiff(previous, current)
    changed = (difference > int(pixel_threshold)).astype(np.uint8)
    valid = mask > 0
    valid_count = max(1, int(valid.sum()))
    changed_valid = changed * valid
    changed_ratio = float(changed_valid.sum()) / valid_count
    mad = _masked_mean(difference, mask)
    ssim = compute_ssim(previous, current, mask)

    bbox_ratio = 0.0
    largest_ratio = 0.0
    if changed_valid.any():
        ys, xs = np.where(changed_valid)
        bbox_ratio = float((xs.max() - xs.min() + 1) * (ys.max() - ys.min() + 1)) / valid_count
        count, _, stats, _ = cv2.connectedComponentsWithStats(changed_valid, connectivity=8)
        if count > 1:
            largest = int(stats[1:, cv2.CC_STAT_AREA].max())
            largest_ratio = largest / valid_count
    return FrameDiff(
        changed_ratio=changed_ratio,
        mad=mad,
        ssim=ssim,
        changed_bbox_ratio=bbox_ratio,
        largest_component_ratio=largest_ratio,
    )


def evaluate_frame_quality(gray: np.ndarray, original_shape: tuple[int, int] | None = None) -> dict[str, float]:
    if gray is None or gray.size == 0:
        return {"mean": 0.0, "std": 0.0, "lap_var": 0.0, "black": 1.0, "near_blank": 1.0, "blurry": 1.0}
    mean = float(gray.mean())
    std = float(gray.std())
    lap_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    return {
        "mean": mean,
        "std": std,
        "lap_var": lap_var,
        "black": 1.0 if (mean < 18.0 and std < 12.0) else 0.0,
        "near_blank": 1.0 if (std < 4.0 and (mean < 12.0 or mean > 245.0)) else 0.0,
        "blurry": 0.0,
    }


def quality_score(quality: dict[str, float], settings: AnalysisSettings) -> float:
    """A 0..1 sharpness/completeness score (not the page confidence)."""
    lap_var = float(quality.get("lap_var", 0.0))
    sharpness = min(1.0, max(0.0, lap_var / max(1.0, settings.blur_good_lap_var)))
    contrast = min(1.0, max(0.0, float(quality.get("std", 0.0)) / 45.0))
    score = 0.72 * sharpness + 0.28 * contrast
    if quality.get("black", 0.0) >= 1.0:
        score *= 0.15
    elif quality.get("near_blank", 0.0) >= 1.0:
        score *= 0.35
    return float(np.clip(score, 0.0, 1.0))


def quality_flags(quality: dict[str, float], settings: AnalysisSettings) -> list[str]:
    flags: list[str] = []
    if quality.get("black", 0.0) >= 1.0 or (
        quality.get("mean", 255.0) < settings.black_luma_threshold
        and quality.get("std", 255.0) < settings.black_std_threshold
    ):
        flags.append("black_frame")
    if quality.get("near_blank", 0.0) >= 1.0:
        flags.append("near_blank")
    if quality.get("lap_var", 0.0) < settings.blur_lap_var_threshold:
        flags.append("blurry")
    return flags

