from __future__ import annotations

import numpy as np
import pytest

from lesson_prep.core.geometry import (
    Rect,
    fit_rect,
    relative_rect,
)
from lesson_prep.core.timecode import format_timecode, parse_timecode
from lesson_prep.stages.video_to_slides.imaging import apply_camera_policy


class TestRect:
    def test_normalized_pixel_roundtrip(self):
        region = Rect(0.1, 0.2, 0.5, 0.4)
        assert region.to_pixels(1000, 800) == (100, 160, 500, 320)
        assert region.to_dict()["x"] == 0.1

    def test_clamped_to_frame(self):
        region = Rect(0.8, 0.9, 0.5, 0.5).clamped()
        assert region.right <= 1.0
        assert region.bottom <= 1.0
        assert region.w == pytest.approx(0.2)
        assert region.h == pytest.approx(0.1)

    def test_relative_rect(self):
        outer = Rect(0.25, 0.25, 0.5, 0.5)
        inner = Rect(0.5, 0.25, 0.25, 0.25)
        rel = relative_rect(inner, outer)
        assert rel is not None
        assert rel.x == pytest.approx(0.5)
        assert rel.y == pytest.approx(0.0)
        assert rel.w == pytest.approx(0.5)
        assert rel.h == pytest.approx(0.5)

    def test_intersection_none(self):
        assert Rect(0, 0, 0.2, 0.2).intersect(Rect(0.8, 0.8, 0.2, 0.2)) is None

    def test_camera_mask_and_ignore(self):
        image = np.full((100, 200, 3), 100, dtype=np.uint8)
        local = Rect(0.5, 0.2, 0.4, 0.5)
        masked, effective = apply_camera_policy(image, local, "mask", border_pixels=0)
        assert effective == "mask"
        assert int(masked[30:60, 110:160].max()) == 0
        assert int(masked[0:10, 0:10].min()) == 100
        white_masked, effective = apply_camera_policy(
            image, local, "mask_white", border_pixels=0
        )
        assert effective == "mask_white"
        assert int(white_masked[30:60, 110:160].min()) == 255
        assert int(white_masked[0:10, 0:10].min()) == 100
        ignored, effective = apply_camera_policy(image, local, "ignore")
        assert effective == "ignore"
        assert np.array_equal(ignored, image)

    def test_camera_crop_touching_edge(self):
        image = np.full((100, 200, 3), 255, dtype=np.uint8)
        local = Rect(0.7, 0.0, 0.3, 0.4)
        cropped, effective = apply_camera_policy(image, local, "crop", border_pixels=0)
        assert effective == "crop"
        assert cropped.shape[1] == 140
        assert cropped.shape[0] == 100

    def test_multiple_camera_policies_apply_independently(self):
        from lesson_prep.stages.video_to_slides.imaging import apply_camera_policies

        image = np.full((100, 200, 3), 80, dtype=np.uint8)
        right_crop = Rect(0.8, 0.0, 0.2, 0.35)
        top_left_white = Rect(0.0, 0.0, 0.2, 0.1)
        processed, modes = apply_camera_policies(
            image,
            [(right_crop, "crop"), (top_left_white, "mask_white")],
            border_pixels=0,
        )
        assert modes == ["crop", "mask_white"]
        assert processed.shape[1] < image.shape[1]
        assert processed.shape[0] == image.shape[0]
        # The second region (5x10..15x7) remains in the cropped image.
        assert int(processed[2:7, 5:15].min()) == 255

    def test_fit_rect_preserves_aspect(self):
        left, top, width, height = fit_rect(1920, 1080, 800, 800)
        assert left == pytest.approx(0)
        assert top == pytest.approx(175)
        assert width == pytest.approx(800)
        assert height == pytest.approx(450)


class TestTimecode:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("01:02:03", 3723.0),
            ("02:03", 123.0),
            ("42.5", 42.5),
            ("00:00:04.250", 4.25),
        ],
    )
    def test_parse(self, text, expected):
        assert parse_timecode(text) == pytest.approx(expected)

    def test_clamped(self):
        assert parse_timecode("00:00:10", duration=5) == 5

    @pytest.mark.parametrize("text", ["", "abc", "1:2:3:4", "00:61:00"])
    def test_invalid(self, text):
        with pytest.raises(ValueError):
            parse_timecode(text)

    def test_format(self):
        assert format_timecode(3723.25, milliseconds=True) == "01:02:03.250"
        assert format_timecode(3723.99) == "01:02:03"

