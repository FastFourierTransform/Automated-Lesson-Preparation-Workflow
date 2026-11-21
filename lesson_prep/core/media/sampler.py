"""Fast FFmpeg-based low-rate frame sampling for long videos."""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Iterator

import numpy as np

from .models import VideoInfo


class SamplerError(RuntimeError):
    pass


class FfmpegSampler:
    """Streams downscaled BGR frames from FFmpeg stdout.

    This is used for the coarse pass, where random-seeking with OpenCV would be
    far too slow on long, long-GOP videos.  It never stores more than one frame
    at a time.
    """

    def __init__(
        self,
        path: str | Path,
        start: float,
        end: float,
        fps: float,
        width: int,
        video_info: VideoInfo | None = None,
    ):
        self.path = str(path)
        self.start = max(0.0, float(start))
        self.end = max(self.start, float(end))
        self.fps = max(0.5, min(float(fps), 30.0))
        self.width = max(64, int(width))
        self.video_info = video_info
        self._process: subprocess.Popen | None = None
        self._stderr_file = None
        self._cancelled = False
        self._out_height = 0

    @staticmethod
    def available() -> bool:
        return shutil.which("ffmpeg") is not None

    def _compute_size(self) -> tuple[int, int]:
        info = self.video_info
        if info is None or info.width <= 0 or info.height <= 0:
            raise SamplerError("缺少视频尺寸信息，无法使用 FFmpeg 粗扫描。")
        src_w, src_h = info.width, info.height
        out_w = min(self.width, src_w)
        out_h = int(round(src_h * out_w / src_w))
        out_h = max(2, out_h // 2 * 2)
        out_w = max(2, out_w // 2 * 2)
        self._out_height = out_h
        return out_w, out_h

    def _command(self, out_w: int, out_h: int) -> list[str]:
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise SamplerError("未找到 FFmpeg。请安装 FFmpeg 并加入 PATH。")
        duration = max(0.01, self.end - self.start)
        vf = f"fps={self.fps:.6f},scale={out_w}:{out_h}:flags=area"
        return [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-ss",
            f"{self.start:.3f}",
            "-t",
            f"{duration:.3f}",
            "-i",
            self.path,
            "-an",
            "-sn",
            "-dn",
            "-vf",
            vf,
            "-pix_fmt",
            "bgr24",
            "-f",
            "rawvideo",
            "pipe:1",
        ]

    def iter_frames(self) -> Iterator[tuple[float, np.ndarray]]:
        if not self.available():
            raise SamplerError("FFmpeg 不可用。")
        out_w, out_h = self._compute_size()
        frame_size = out_w * out_h * 3
        command = self._command(out_w, out_h)
        creationflags = 0
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            creationflags = subprocess.CREATE_NO_WINDOW
        self._stderr_file = tempfile.TemporaryFile()
        try:
            self._process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=self._stderr_file,
                stdin=subprocess.DEVNULL,
                bufsize=0,
                creationflags=creationflags,
            )
        except OSError as exc:
            self._stderr_file.close()
            self._stderr_file = None
            raise SamplerError(f"无法启动 FFmpeg：{exc}") from exc

        interval = 1.0 / self.fps
        index = 0
        stdout = self._process.stdout
        try:
            while not self._cancelled:
                data = self._read_exact(stdout, frame_size)
                if data is None:
                    break
                frame = np.frombuffer(data, dtype=np.uint8).reshape((out_h, out_w, 3)).copy()
                timestamp = self.start + index * interval
                if timestamp > self.end + interval:
                    break
                yield timestamp, frame
                index += 1
            if not self._cancelled:
                returncode = self._process.wait()
                if returncode != 0:
                    message = self._stderr_text() or "FFmpeg 无法完整解码该视频。"
                    raise SamplerError(message)
        finally:
            self.close()

    @staticmethod
    def _read_exact(stream, size: int) -> bytes | None:
        chunks: list[bytes] = []
        remaining = size
        while remaining > 0:
            block = stream.read(remaining)
            if not block:
                return None
            chunks.append(block)
            remaining -= len(block)
        return b"".join(chunks) if len(chunks) > 1 else chunks[0]

    def _stderr_text(self) -> str:
        if not self._stderr_file:
            return ""
        try:
            self._stderr_file.seek(0)
            return self._stderr_file.read().decode("utf-8", errors="replace").strip()
        except Exception:
            return ""

    def cancel(self) -> None:
        self._cancelled = True
        if self._process is not None and self._process.poll() is None:
            try:
                self._process.terminate()
            except OSError:
                pass

    def close(self) -> None:
        process = self._process
        if process is not None:
            if process.poll() is None:
                try:
                    process.terminate()
                    process.wait(timeout=3)
                except Exception:
                    try:
                        process.kill()
                    except OSError:
                        pass
            if process.stdout:
                try:
                    process.stdout.close()
                except OSError:
                    pass
            self._process = None
        if self._stderr_file is not None:
            try:
                self._stderr_file.close()
            except OSError:
                pass
            self._stderr_file = None
