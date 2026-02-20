"""Video manager module for video visualization tool."""

from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
import subprocess

import cv2
import numpy as np

from visualization.filters.base import BaseFilter

FPS_TOLERANCE = 0.01


def _detect_audio_ffprobe(path: Path) -> bool:
    """Check if the video file has an audio track using ffprobe.

    Args:
        path: Path to the video file.

    Returns:
        True if an audio stream is found, False otherwise.
        Returns False if ffprobe is not found or fails.
    """
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "a",
                "-show_entries",
                "stream=codec_type",
                "-of",
                "csv=p=0",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if result.returncode != 0:
            return False
        output = result.stdout.strip() if result.stdout else ""
        return "audio" in output
    except FileNotFoundError:
        return False
    except subprocess.TimeoutExpired:
        return False


@dataclass
class VideoInfo:
    """Metadata for a loaded video."""

    path: Path
    filename: str
    width: int
    height: int
    fps: float
    frame_count: int
    has_audio: bool
    duration_sec: float


class VideoEntry:
    """Represents a single loaded video in the session."""

    def __init__(
        self,
        video_id: int,
        info: VideoInfo,
        label: str | None = None,
        filter: BaseFilter | None = None,
    ) -> None:
        self.video_id = video_id
        self.info = info
        self.label = label if label is not None else f"{video_id}: {info.filename}"
        self.filter = filter
        self._capture: cv2.VideoCapture | None = None
        self._next_frame_idx: int = 0

    def _ensure_capture(self) -> cv2.VideoCapture | None:
        """Ensure the video capture is opened. Return None if failed."""
        if self._capture is not None:
            return self._capture
        cap = cv2.VideoCapture(str(self.info.path))
        if not cap.isOpened():
            return None
        self._capture = cap
        self._next_frame_idx = 0
        return cap

    @property
    def capture(self) -> cv2.VideoCapture:
        """Opened cv2.VideoCapture handle."""
        cap = self._ensure_capture()
        if cap is None:
            raise RuntimeError(
                f"Failed to open video: {self.info.path}"
            )
        return cap

    def read_frame(self, frame_idx: int) -> np.ndarray | None:
        """Seek to frame_idx and decode. Return BGR numpy array or None on failure.

        If frame_idx exceeds the video's frame count the last frame is returned.
        Avoids costly seek when the requested frame is already the next in sequence.
        """
        cap = self._ensure_capture()
        if cap is None:
            return None
        clamped = min(frame_idx, max(0, self.info.frame_count - 1))
        if clamped != self._next_frame_idx:
            cap.set(cv2.CAP_PROP_POS_FRAMES, clamped)
        ret, frame = cap.read()
        if not ret or frame is None:
            self._next_frame_idx = -1
            return None
        self._next_frame_idx = clamped + 1
        return frame

    def close(self) -> None:
        """Release the capture."""
        if self._capture is not None:
            self._capture.release()
            self._next_frame_idx = 0
            self._capture = None


class VideoManager:
    """Manages all loaded videos."""

    def __init__(self) -> None:
        self._entries: list[VideoEntry] = []
        self._next_id = 0

    def load_video(self, path: str | Path) -> VideoEntry:
        """Open video with cv2.VideoCapture, probe metadata, and add to session."""
        path = Path(path).resolve()
        if not path.exists():
            raise FileNotFoundError(f"Video file not found: {path}")

        cap = cv2.VideoCapture(str(path))
        if not cap.isOpened():
            cap.release()
            raise RuntimeError(f"Cannot open video file: {path}")

        try:
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps = cap.get(cv2.CAP_PROP_FPS)
            frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

            if fps <= 0 or not np.isfinite(fps):
                fps = 0.0
            if frame_count < 0:
                frame_count = 0

            duration_sec = frame_count / fps if fps > 0 else 0.0

            if self._entries:
                existing_fps = self._entries[0].info.fps
                if abs(fps - existing_fps) > FPS_TOLERANCE:
                    cap.release()
                    raise ValueError(
                        f"Video fps ({fps}) does not match session fps ({existing_fps}). "
                        "All videos must have the same framerate (tolerance 0.01)."
                    )

            has_audio = _detect_audio_ffprobe(path)
            filename = path.name

            info = VideoInfo(
                path=path,
                filename=filename,
                width=width,
                height=height,
                fps=fps,
                frame_count=frame_count,
                has_audio=has_audio,
                duration_sec=duration_sec,
            )

            video_id = self._next_id
            self._next_id += 1
            entry = VideoEntry(video_id=video_id, info=info)
            entry._capture = cap
            self._entries.append(entry)
            return entry
        except Exception:
            cap.release()
            raise

    def remove_video(self, video_id: int) -> None:
        """Close and remove video by ID."""
        for i, entry in enumerate(self._entries):
            if entry.video_id == video_id:
                entry.close()
                self._entries.pop(i)
                return
        raise KeyError(f"Video with id {video_id} not found")

    def clear(self) -> None:
        """Close and remove all videos."""
        for entry in self._entries:
            entry.close()
        self._entries.clear()
        self._next_id = 0

    def get_video(self, video_id: int) -> VideoEntry | None:
        """Get video entry by ID."""
        for entry in self._entries:
            if entry.video_id == video_id:
                return entry
        return None

    def get_all_videos(self) -> list[VideoEntry]:
        """Get all loaded video entries."""
        return list(self._entries)

    @property
    def video_count(self) -> int:
        """Number of loaded videos."""
        return len(self._entries)

    @property
    def session_fps(self) -> float | None:
        """FPS of loaded videos, None if no videos loaded."""
        if not self._entries:
            return None
        return self._entries[0].info.fps

    @property
    def max_frame_count(self) -> int:
        """Maximum frame_count across all loaded videos. Returns 0 if no videos."""
        if not self._entries:
            return 0
        return max(e.info.frame_count for e in self._entries)

    @property
    def max_resolution(self) -> tuple[int, int]:
        """(max_width, max_height) across all loaded videos."""
        if not self._entries:
            return (0, 0)
        max_w = max(e.info.width for e in self._entries)
        max_h = max(e.info.height for e in self._entries)
        return (max_w, max_h)


class FrameCache:
    """LRU cache for decoded frames to enable fast scrubbing."""

    def __init__(self, max_size: int = 120) -> None:
        """Initialize the cache.

        Args:
            max_size: Maximum number of frames to cache per video.
        """
        self._max_size = max_size
        self._cache: dict[int, OrderedDict[int, np.ndarray]] = {}

    def _get_video_cache(self, video_id: int) -> OrderedDict[int, np.ndarray]:
        """Get or create the per-video LRU cache."""
        if video_id not in self._cache:
            self._cache[video_id] = OrderedDict()
        return self._cache[video_id]

    def get(self, video_id: int, frame_idx: int) -> np.ndarray | None:
        """Get a cached frame if present."""
        video_cache = self._cache.get(video_id)
        if video_cache is None or frame_idx not in video_cache:
            return None
        frame = video_cache[frame_idx]
        video_cache.move_to_end(frame_idx)
        return frame

    def put(self, video_id: int, frame_idx: int, frame: np.ndarray) -> None:
        """Cache a decoded frame. Evict oldest for this video if at capacity."""
        video_cache = self._get_video_cache(video_id)

        if frame_idx in video_cache:
            video_cache.move_to_end(frame_idx)
            video_cache[frame_idx] = frame
            return

        while len(video_cache) >= self._max_size:
            video_cache.popitem(last=False)

        video_cache[frame_idx] = frame

    def clear(self, video_id: int | None = None) -> None:
        """Clear cache for a specific video or all videos."""
        if video_id is None:
            self._cache.clear()
            return

        if video_id in self._cache:
            del self._cache[video_id]
