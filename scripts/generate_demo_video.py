"""Generate a synthetic lecture video used for automated end-to-end tests.

It contains:
- moving intro/outro segments outside the content range,
- five slides with hard cuts, a cross-fade and a wipe,
- progressive pen annotations on one slide,
- a small local pop-in animation on another slide,
- a continuously changing picture-in-picture "teacher camera" that must be
  excluded from page-change detection.

This is a synthetic substitute.  It deliberately does not reproduce real
compression, codec, camera, or handwriting variability.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import cv2
import numpy as np

WIDTH = 1280
HEIGHT = 720
FPS = 30
DURATION = 42.0
CONTENT_START = 4.0
CONTENT_END = 38.0
CAMERA_REGION = (0.746, 0.028, 0.231, 0.282)  # normalized x, y, w, h


def _new_canvas(color=(248, 248, 250)) -> np.ndarray:
    return np.full((HEIGHT, WIDTH, 3), color, dtype=np.uint8)


def _text(img, text, org, scale=1.0, color=(35, 40, 60), thickness=2):
    cv2.putText(img, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, color, thickness, cv2.LINE_AA)


def _slide_one() -> np.ndarray:
    img = _new_canvas((248, 248, 250))
    cv2.rectangle(img, (0, 0), (WIDTH, 92), (45, 62, 110), -1)
    _text(img, "Deep Learning Fundamentals", (55, 62), 1.25, (255, 255, 255), 2)
    _text(img, "Lecture 1  |  Neural Networks", (70, 180), 1.6, (38, 48, 92), 3)
    cv2.line(img, (70, 215), (670, 215), (220, 150, 60), 8)
    for i, line in enumerate(
        [
            "Neurons, layers and activation functions",
            "Forward propagation and loss",
            "A first look at gradient descent",
        ]
    ):
        y = 300 + i * 92
        cv2.circle(img, (100, y - 10), 11, (220, 150, 60), -1)
        _text(img, line, (135, y), 0.85, (55, 60, 75), 2)
    cv2.rectangle(img, (760, 300), (1130, 570), (235, 240, 248), -1)
    cv2.rectangle(img, (760, 300), (1130, 570), (150, 160, 190), 2)
    _text(img, "input", (790, 345), 0.65, (80, 90, 120), 2)
    cv2.circle(img, (860, 430), 32, (90, 140, 220), -1)
    cv2.circle(img, (990, 430), 32, (90, 140, 220), -1)
    cv2.circle(img, (1090, 430), 32, (220, 150, 60), -1)
    cv2.line(img, (892, 430), (958, 430), (90, 100, 120), 3)
    cv2.line(img, (1022, 430), (1058, 430), (90, 100, 120), 3)
    _text(img, "x1", (846, 510), 0.6, (80, 90, 120), 2)
    _text(img, "x2", (976, 510), 0.6, (80, 90, 120), 2)
    _text(img, "output", (1058, 510), 0.6, (80, 90, 120), 2)
    _text(img, "1 / 5", (1160, 680), 0.65, (130, 135, 150), 1)
    return img


def _slide_two() -> np.ndarray:
    img = _new_canvas((252, 249, 242))
    cv2.rectangle(img, (0, 0), (14, HEIGHT), (70, 120, 150), -1)
    _text(img, "Backpropagation", (70, 105), 1.7, (45, 70, 100), 3)
    _text(img, "How gradients flow backwards through the graph", (72, 160), 0.72, (90, 95, 110), 2)
    cv2.line(img, (72, 190), (700, 190), (210, 140, 80), 5)
    for i, line in enumerate(
        [
            "Compute the output and the loss",
            "Apply the chain rule layer by layer",
            "Accumulate gradients for each parameter",
            "Update weights with the optimiser",
        ]
    ):
        _text(img, f"{i + 1}.  {line}", (85, 270 + i * 72), 0.76, (55, 58, 68), 2)
    # A simple computational graph.
    boxes = [(820, 250), (990, 250), (990, 430), (820, 430)]
    labels = ["x", "Wx + b", "loss", "dW"]
    for (x, y), label in zip(boxes, labels):
        cv2.rectangle(img, (x, y), (x + 130, y + 82), (240, 244, 250), -1)
        cv2.rectangle(img, (x, y), (x + 130, y + 82), (140, 155, 185), 2)
        _text(img, label, (x + 12, y + 50), 0.62, (50, 70, 110), 2)
    cv2.arrowedLine(img, (950, 291), (990, 291), (90, 100, 120), 3, tipLength=0.2)
    cv2.arrowedLine(img, (1055, 332), (1055, 430), (90, 100, 120), 3, tipLength=0.2)
    cv2.arrowedLine(img, (990, 471), (950, 471), (90, 100, 120), 3, tipLength=0.2)
    cv2.arrowedLine(img, (885, 430), (885, 332), (90, 100, 120), 3, tipLength=0.2)
    _text(img, "2 / 5", (1160, 680), 0.65, (130, 135, 150), 1)
    return img


def _slide_three() -> np.ndarray:
    img = _new_canvas((246, 246, 246))
    cv2.rectangle(img, (0, 0), (WIDTH, 100), (35, 90, 70), -1)
    _text(img, "Optimization", (55, 68), 1.35, (245, 255, 250), 2)
    _text(img, "Finding parameters that reduce the loss", (70, 175), 0.85, (55, 70, 70), 2)
    # Loss curve.
    points = []
    for i in range(0, 101):
        x = 120 + i * 5
        y = 560 - int(290 * math.exp(-i / 26.0)) - int(20 * math.sin(i / 4.0) * math.exp(-i / 40.0))
        points.append((x, y))
    cv2.polylines(img, [np.array(points, dtype=np.int32)], False, (50, 115, 210), 5)
    cv2.line(img, (115, 580), (700, 580), (90, 95, 105), 2)
    cv2.line(img, (120, 590), (120, 220), (90, 95, 105), 2)
    _text(img, "loss", (75, 225), 0.65, (70, 75, 85), 2)
    _text(img, "iterations", (600, 620), 0.65, (70, 75, 85), 2)
    for i, (title, body) in enumerate(
        [
            ("SGD", "simple, noisy updates"),
            ("Momentum", "smooths the trajectory"),
            ("Adam", "adaptive per-parameter steps"),
        ]
    ):
        y = 250 + i * 115
        cv2.rectangle(img, (760, y), (1160, y + 88), (235, 243, 238), -1)
        cv2.rectangle(img, (760, y), (1160, y + 88), (150, 180, 165), 2)
        _text(img, title, (785, y + 37), 0.72, (35, 85, 65), 2)
        _text(img, body, (785, y + 68), 0.52, (75, 85, 80), 1)
    _text(img, "3 / 5", (1160, 680), 0.65, (130, 135, 150), 1)
    return img


def _slide_four() -> np.ndarray:
    img = _new_canvas((250, 247, 252))
    cv2.rectangle(img, (0, 0), (WIDTH, 90), (105, 65, 130), -1)
    _text(img, "Regularization", (58, 62), 1.35, (255, 250, 255), 2)
    _text(img, "Reduce overfitting and improve generalization", (70, 165), 0.82, (70, 60, 80), 2)
    for i, (title, body) in enumerate(
        [
            ("Dropout", "randomly deactivate units during training"),
            ("Weight decay", "penalize large parameter values"),
            ("Early stopping", "stop when validation loss rises"),
            ("Data augmentation", "create useful training variations"),
        ]
    ):
        y = 235 + i * 96
        cv2.rectangle(img, (90, y), (690, y + 72), (240, 234, 246), -1)
        cv2.line(img, (90, y), (90, y + 72), (150, 100, 180), 8)
        _text(img, title, (120, y + 32), 0.68, (85, 55, 110), 2)
        _text(img, body, (120, y + 58), 0.5, (90, 85, 95), 1)
    cv2.circle(img, (955, 380), 150, (235, 225, 245), -1)
    cv2.circle(img, (955, 380), 150, (160, 120, 185), 3)
    _text(img, "generalize", (870, 370), 0.68, (100, 65, 130), 2)
    _text(img, "not memorize", (860, 410), 0.55, (110, 80, 140), 1)
    _text(img, "4 / 5", (1160, 680), 0.65, (130, 135, 150), 1)
    return img


def _slide_five() -> np.ndarray:
    img = _new_canvas((247, 249, 252))
    cv2.rectangle(img, (0, 0), (WIDTH, 110), (35, 55, 95), -1)
    _text(img, "Summary", (60, 74), 1.45, (250, 252, 255), 2)
    _text(img, "What you should remember", (70, 185), 0.85, (55, 65, 85), 2)
    bullets = [
        "Neural networks compose differentiable layers",
        "Backpropagation applies the chain rule efficiently",
        "Optimisers control how parameters move",
        "Regularization keeps the model honest",
    ]
    for i, line in enumerate(bullets):
        y = 275 + i * 82
        cv2.rectangle(img, (95, y - 26), (112, y - 9), (220, 145, 55), -1)
        _text(img, line, (140, y), 0.72, (50, 58, 75), 2)
    cv2.rectangle(img, (70, 610), (1180, 675), (232, 238, 248), -1)
    _text(img, "Next: convolutional networks and visual feature learning", (95, 651), 0.62, (60, 75, 110), 2)
    _text(img, "5 / 5", (1160, 700), 0.6, (130, 135, 150), 1)
    return img


def _intro(t: float) -> np.ndarray:
    img = _new_canvas((22, 29, 48))
    for i in range(14):
        x = int((math.sin(t * 0.7 + i * 0.9) * 0.5 + 0.5) * WIDTH)
        y = int((math.cos(t * 0.5 + i * 1.3) * 0.5 + 0.5) * HEIGHT)
        cv2.circle(img, (x, y), 18 + i * 4, (40 + i * 6, 65 + i * 3, 105 + i * 4), -1)
    _text(img, "DEEP LEARNING", (315, 330), 1.8, (245, 248, 255), 4)
    _text(img, "FUNDAMENTALS", (352, 420), 1.3, (180, 205, 245), 2)
    _text(img, "a short course", (510, 480), 0.8, (170, 180, 205), 1)
    return img


def _outro(t: float) -> np.ndarray:
    img = _new_canvas((18, 22, 34))
    angle = t * 0.8
    for i in range(8):
        a = angle + i * math.pi / 4
        x = int(WIDTH / 2 + math.cos(a) * 280)
        y = int(HEIGHT / 2 + math.sin(a) * 190)
        cv2.circle(img, (x, y), 25, (70, 100, 160), -1)
    _text(img, "Thanks for watching", (350, 340), 1.4, (245, 248, 255), 3)
    _text(img, "See you in the next lesson", (435, 410), 0.75, (175, 190, 220), 2)
    return img


def _blend_overlay(base: np.ndarray, overlay: np.ndarray, alpha: float) -> np.ndarray:
    return cv2.addWeighted(base, 1.0 - alpha, overlay, alpha, 0)


def _pen_overlay(t: float) -> np.ndarray:
    """Animate red pen marks on slide two between 12.5s and 16s."""
    overlay = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
    pen_color = (30, 30, 220)
    if t < 12.5 or t > 16.0:
        return overlay
    progress = (t - 12.5) / 3.5
    # Underline the title.
    x2 = int(520 + 190 * min(1.0, progress * 4))
    cv2.line(overlay, (72, 122), (x2, 122), pen_color, 6, cv2.LINE_AA)
    # Circle the chain-rule bullet.
    if progress > 0.25:
        p = min(1.0, (progress - 0.25) / 0.25)
        cv2.ellipse(
            overlay,
            (392, 362),
            (240, 44),
            0,
            0,
            int(360 * p),
            pen_color,
            4,
            cv2.LINE_AA,
        )
    # Arrow towards dW.
    if progress > 0.55:
        p = min(1.0, (progress - 0.55) / 0.25)
        end = (int(875 + 90 * p), 471)
        cv2.arrowedLine(overlay, (900, 540), end, pen_color, 5, cv2.LINE_AA, tipLength=0.2)
    # A few short strokes.
    if progress > 0.8:
        for i in range(4):
            cv2.line(overlay, (760 + i * 14, 590), (800 + i * 14, 610), pen_color, 3, cv2.LINE_AA)
    return overlay


def _draw_camera(frame: np.ndarray, t: float) -> np.ndarray:
    x, y, w, h = CAMERA_REGION
    left, top = int(x * WIDTH), int(y * HEIGHT)
    right, bottom = int((x + w) * WIDTH), int((y + h) * HEIGHT)
    roi = frame[top:bottom, left:right]
    # A constantly changing background so that including the camera in the
    # analysis would produce false change events.
    ph = t * 1.1
    for row in range(0, roi.shape[0], 4):
        color = (
            int(70 + 40 * math.sin(ph + row * 0.05)),
            int(90 + 45 * math.cos(ph * 0.8 + row * 0.03)),
            int(120 + 55 * math.sin(ph * 1.3 + row * 0.02)),
        )
        roi[row : row + 4, :] = color
    cx = int(roi.shape[1] * (0.5 + 0.20 * math.sin(t * 0.9)))
    cy = int(roi.shape[0] * (0.52 + 0.10 * math.sin(t * 1.7 + 1.0)))
    cv2.circle(roi, (cx, cy), 54, (205, 185, 165), -1)
    cv2.circle(roi, (cx - 18, cy - 12), 6, (45, 45, 55), -1)
    cv2.circle(roi, (cx + 18, cy - 12), 6, (45, 45, 55), -1)
    cv2.ellipse(roi, (cx, cy + 18), (22, 11), 0, 0, 180, (80, 60, 60), 3)
    if math.sin(t * 2.0) > 0:
        cv2.circle(roi, (cx, cy), 62, (70, 210, 240), 2)
    _text(roi, "TEACHER", (10, 30), 0.55, (250, 250, 250), 2)
    cv2.rectangle(roi, (0, 0), (roi.shape[1] - 1, roi.shape[0] - 1), (30, 35, 45), 3)
    return frame


def _content_frame(t: float) -> np.ndarray:
    s1, s2, s3, s4, s5 = _slide_one(), _slide_two(), _slide_three(), _slide_four(), _slide_five()
    if t < 10.0:
        frame = s1.copy()
    elif t < 18.0:
        frame = cv2.addWeighted(s2, 1.0, _pen_overlay(t), 1.0, 0)
    elif t < 18.8:
        alpha = (t - 18.0) / 0.8
        frame = _blend_overlay(s2, s3, alpha)
    elif t < 25.0:
        frame = s3.copy()
    elif t < 25.8:
        # Vertical wipe with a bright loading band.
        frame = s3.copy()
        position = int(WIDTH * (t - 25.0) / 0.8)
        frame[:, :position] = s4[:, :position]
        band_start = max(0, position - 35)
        band_end = min(WIDTH, position + 35)
        if band_end > band_start:
            frame[:, band_start:band_end] = (245, 245, 245)
    elif t < 33.0:
        frame = s4.copy()
        # A small local subtitle pop-in; should not become a new page.
        if t >= 30.0:
            cv2.rectangle(frame, (860, 555), (1115, 610), (230, 220, 245), -1)
            _text(frame, "regularization = control", (875, 588), 0.45, (110, 75, 140), 1)
    elif t < 38.0:
        frame = s5.copy()
    else:
        frame = _outro(t)
    return frame


def frame_at(t: float) -> np.ndarray:
    if t < CONTENT_START:
        frame = _intro(t)
    elif t < CONTENT_END:
        frame = _content_frame(t)
    else:
        frame = _outro(t)
    return _draw_camera(frame, t)


def create_demo_video(path: str | Path, fps: int = FPS, duration: float = DURATION) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(path), fourcc, fps, (WIDTH, HEIGHT))
    if not writer.isOpened():
        raise RuntimeError("无法创建测试视频（mp4v 编码器不可用）")
    try:
        frame_count = int(round(duration * fps))
        for index in range(frame_count):
            writer.write(frame_at(index / fps))
    finally:
        writer.release()
    if not path.exists() or path.stat().st_size == 0:
        raise RuntimeError("测试视频写入失败")
    return path


def main(argv: list[str] | None = None) -> int:
    argv = argv or sys.argv[1:]
    target = Path(argv[0]) if argv else Path("test_artifacts/demo_lecture.mp4")
    create_demo_video(target)
    print(f"created {target.resolve()} ({target.stat().st_size / 1024 / 1024:.2f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
