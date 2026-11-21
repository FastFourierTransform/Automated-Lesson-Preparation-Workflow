"""Camera-region handling for the video-to-slides stage.

Camera regions are stored in source-video coordinates but applied to a PPT
crop.  Cropping changes the coordinate system, so strips are remapped as they
are removed.
"""
from __future__ import annotations

import numpy as np

from ...core.geometry import Rect, crop_rect, relative_rect


def apply_camera_policies(
    cropped_image: np.ndarray,
    camera_regions: list[tuple[Rect | None, str]] | None,
    border_pixels: int = 1,
) -> tuple[np.ndarray, list[str]]:
    """Apply multiple camera policies sequentially to a cropped slide.

    Regions and modes are in the coordinate system of the original cropped
    image.  Cropping changes that coordinate system, so subsequent regions are
    remapped as strips are removed.  Returns the processed image and the
    effective mode for every configured camera (including ``ignore``).
    """
    image = cropped_image.copy()
    if not camera_regions:
        return image, []
    original_h, original_w = image.shape[:2]
    left_cut = 0
    top_cut = 0
    pad = max(0, int(border_pixels))
    effective_modes: list[str] = []

    for camera_local, camera_mode in camera_regions:
        mode = getattr(camera_mode, "value", camera_mode)
        if camera_local is None or not camera_local.is_valid() or mode == "ignore":
            effective_modes.append("ignore")
            continue
        x_orig, y_orig, cw, ch = camera_local.to_pixels(original_w, original_h)
        x = x_orig - left_cut
        y = y_orig - top_cut
        cur_h, cur_w = image.shape[:2]
        x0 = max(0, x)
        y0 = max(0, y)
        x1 = min(cur_w, x + cw)
        y1 = min(cur_h, y + ch)
        if x1 <= x0 or y1 <= y0:
            effective_modes.append("ignore")
            continue

        if mode in ("mask", "mask_white"):
            fill_value = 255 if mode == "mask_white" else 0
            image[
                max(0, y0 - pad) : min(cur_h, y1 + pad),
                max(0, x0 - pad) : min(cur_w, x1 + pad),
            ] = fill_value
            effective_modes.append(mode)
            continue

        if mode == "crop":
            edge_tolerance = max(pad, 5)
            touches_left = x <= edge_tolerance
            touches_right = x + cw >= cur_w - edge_tolerance
            touches_top = y <= edge_tolerance
            touches_bottom = y + ch >= cur_h - edge_tolerance
            # A camera spanning the whole axis cannot be removed by cropping
            # that axis without deleting the slide; mask it instead.
            if touches_left and touches_right:
                touches_left = touches_right = False
            if touches_top and touches_bottom:
                touches_top = touches_bottom = False
            if touches_left:
                new_x = min(cur_w - 2, max(0, x + cw - pad))
                image = image[:, new_x:].copy()
                left_cut += new_x
                effective_modes.append("crop")
                continue
            if touches_right:
                new_w = max(2, x + pad)
                image = image[:, :new_w].copy()
                effective_modes.append("crop")
                continue
            if touches_top:
                new_y = min(cur_h - 2, max(0, y + ch - pad))
                image = image[new_y:, :].copy()
                top_cut += new_y
                effective_modes.append("crop")
                continue
            if touches_bottom:
                new_h = max(2, y + pad)
                image = image[:new_h, :].copy()
                effective_modes.append("crop")
                continue
            image[
                max(0, y0 - pad) : min(cur_h, y1 + pad),
                max(0, x0 - pad) : min(cur_w, x1 + pad),
            ] = 0
            effective_modes.append("mask")
            continue

        effective_modes.append("ignore")
    return image, effective_modes


def apply_camera_policy(
    cropped_image: np.ndarray,
    camera_region_local: Rect | None,
    camera_mode: str,
    border_pixels: int = 1,
) -> tuple[np.ndarray, str]:
    """Apply one camera policy. Kept as a convenience for single-region uses."""
    if camera_region_local is None:
        return cropped_image.copy(), "ignore"
    image, modes = apply_camera_policies(
        cropped_image,
        [(camera_region_local, camera_mode)],
        border_pixels=border_pixels,
    )
    return image, modes[0] if modes else "ignore"


def camera_adjusted_crop(
    image: np.ndarray,
    ppt_region: Rect,
    camera_region: Rect | None,
    camera_mode: str,
    border_pixels: int = 1,
) -> np.ndarray:
    """Crop the PPT area and apply the configured camera handling policy."""
    crop = crop_rect(image, ppt_region)
    local = relative_rect(camera_region, ppt_region) if camera_region else None
    processed, _ = apply_camera_policy(crop, local, camera_mode, border_pixels)
    return processed
