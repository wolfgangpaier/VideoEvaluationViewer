"""Exporter module for rendering composed video views to a single output file."""

import math
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path

import cv2
import numpy as np

from visualization.core.video_manager import FrameCache, VideoEntry, VideoManager
from visualization.filters.base import BaseFilter


def resize_with_letterbox(frame: np.ndarray, target_w: int, target_h: int) -> np.ndarray:
    """Resize frame to fit within target_w x target_h, preserving aspect ratio.

    Center the resized frame on a black canvas of target_w x target_h.
    """
    h, w = frame.shape[:2]
    if w <= 0 or h <= 0:
        return np.zeros((target_h, target_w, 3), dtype=np.uint8)

    scale = min(target_w / w, target_h / h)
    new_w = max(1, int(round(w * scale)))
    new_h = max(1, int(round(h * scale)))

    resized = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_LINEAR)

    canvas = np.zeros((target_h, target_w, 3), dtype=np.uint8)
    y0 = (target_h - new_h) // 2
    x0 = (target_w - new_w) // 2
    canvas[y0 : y0 + new_h, x0 : x0 + new_w] = resized

    return canvas


def _crop_to_roi(
    frame: np.ndarray,
    roi: tuple[float, float, float, float] | None,
) -> np.ndarray:
    """Crop frame to normalised ROI (x1, y1, x2, y2). No-op if roi is None."""
    if roi is None:
        return frame
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = roi
    cx1 = max(0, int(x1 * w))
    cy1 = max(0, int(y1 * h))
    cx2 = min(w, int(x2 * w))
    cy2 = min(h, int(y2 * h))
    if cx2 <= cx1 or cy2 <= cy1:
        return frame
    return frame[cy1:cy2, cx1:cx2]


def _draw_text_outlined(
    img: np.ndarray,
    text: str,
    org: tuple[int, int],
    font_scale: float,
    thickness: int = 1,
) -> None:
    """Draw white text with a thin black outline for readability."""
    font = cv2.FONT_HERSHEY_SIMPLEX
    cv2.putText(img, text, org, font, font_scale, (0, 0, 0), thickness + 1, cv2.LINE_AA)
    cv2.putText(img, text, org, font, font_scale, (255, 255, 255), thickness, cv2.LINE_AA)


class Exporter:
    """Renders the side-by-side composed view of all loaded videos into a single output video."""

    def __init__(self, video_manager: VideoManager, frame_cache: FrameCache) -> None:
        self._video_manager = video_manager
        self._frame_cache = frame_cache

    def _get_frame(self, entry: VideoEntry, frame_idx: int) -> np.ndarray | None:
        frame = self._frame_cache.get(entry.video_id, frame_idx)
        if frame is not None:
            return frame
        frame = entry.read_frame(frame_idx)
        if frame is not None:
            self._frame_cache.put(entry.video_id, frame_idx, frame)
        return frame

    def _get_reference_frame(
        self, ref_video_id: int, frame_idx: int, videos: list[VideoEntry]
    ) -> np.ndarray | None:
        for v in videos:
            if v.video_id == ref_video_id:
                return self._get_frame(v, frame_idx)
        return None

    def export(
        self,
        output_path: str | Path,
        export_width: int | None = None,
        export_height: int | None = None,
        audio_source_path: Path | None = None,
        rows: int = 1,
        roi: tuple[float, float, float, float] | None = None,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> None:
        """Export the composed view to a video file.

        Args:
            output_path: Path for the output video file.
            export_width: Optional total export width.
            export_height: Optional total export height.
            audio_source_path: Optional path to audio file to mux into output.
            rows: Number of rows in the grid layout.
            roi: Optional normalised ROI (x1, y1, x2, y2) to crop all frames.
            progress_callback: Optional callback(frame_idx, total_frames).
        """
        output_path = Path(output_path).resolve()
        videos = self._video_manager.get_all_videos()
        if not videos:
            raise ValueError("No videos loaded; cannot export.")

        video_count = len(videos)
        max_w, max_h = self._video_manager.max_resolution
        cols = math.ceil(video_count / rows)
        total_frames = self._video_manager.max_frame_count
        fps = self._video_manager.session_fps
        if fps is None or fps <= 0:
            fps = 25.0

        if export_width is not None and export_height is not None:
            panel_width = export_width // cols
            panel_height = export_height // rows
            canvas_width = export_width
            canvas_height = export_height
        elif export_width is not None:
            panel_width = export_width // cols
            panel_height = int(round(panel_width * max_h / max_w)) if max_w > 0 else panel_width
            canvas_width = export_width
            canvas_height = rows * panel_height
        elif export_height is not None:
            panel_height = export_height // rows
            panel_width = int(round(panel_height * max_w / max_h)) if max_h > 0 else panel_height
            canvas_height = export_height
            canvas_width = cols * panel_width
        else:
            panel_width = max_w
            panel_height = max_h
            canvas_width = cols * panel_width
            canvas_height = rows * panel_height

        panel_width = max(1, panel_width)
        panel_height = max(1, panel_height)

        use_audio = audio_source_path is not None and Path(audio_source_path).exists()
        final_output = output_path

        if use_audio:
            with tempfile.NamedTemporaryFile(
                suffix=".mp4", prefix="export_", delete=False
            ) as tmp:
                write_path = Path(tmp.name)
        else:
            write_path = output_path

        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(
            str(write_path), fourcc, fps, (canvas_width, canvas_height)
        )
        if not writer.isOpened():
            raise RuntimeError(f"Failed to create VideoWriter for: {write_path}")

        label_font_scale = max(0.4, min(1.2, panel_height / 500.0))
        label_thickness = max(1, round(panel_height / 500))
        frame_num_scale = max(0.4, min(1.0, canvas_height / 600.0))
        frame_num_thickness = max(1, round(canvas_height / 600))

        try:
            for frame_idx in range(total_frames):
                canvas = np.zeros((canvas_height, canvas_width, 3), dtype=np.uint8)

                for i, entry in enumerate(videos):
                    frame = self._get_frame(entry, frame_idx)
                    if frame is None:
                        frame = np.zeros((panel_height, panel_width, 3), dtype=np.uint8)

                    frame = _crop_to_roi(frame, roi)

                    if entry.filter is not None:
                        flt: BaseFilter = entry.filter
                        ref_frame = None
                        if flt.needs_reference:
                            ref_video_id = getattr(flt, "ref_video_id", None)
                            if ref_video_id is not None:
                                ref_frame = self._get_reference_frame(
                                    ref_video_id, frame_idx, videos
                                )
                                ref_frame = _crop_to_roi(ref_frame, roi) if ref_frame is not None else None
                        frame = flt.apply(frame, ref_frame)

                    panel = resize_with_letterbox(frame, panel_width, panel_height)

                    (txt_w, _), _ = cv2.getTextSize(
                        entry.label, cv2.FONT_HERSHEY_SIMPLEX,
                        label_font_scale, label_thickness,
                    )
                    label_x = (panel_width - txt_w) // 2
                    label_y = int(label_font_scale * 30) + 4
                    _draw_text_outlined(
                        panel, entry.label, (label_x, label_y),
                        label_font_scale, label_thickness,
                    )

                    row_idx = i // cols
                    col_idx = i % cols
                    y0 = row_idx * panel_height
                    x0 = col_idx * panel_width
                    canvas[y0 : y0 + panel_height, x0 : x0 + panel_width] = panel

                frame_label = f"Frame: {frame_idx}"
                _draw_text_outlined(
                    canvas, frame_label, (10, int(frame_num_scale * 30) + 4),
                    frame_num_scale, frame_num_thickness,
                )

                writer.write(canvas)

                if progress_callback is not None:
                    progress_callback(frame_idx, total_frames)

        finally:
            writer.release()

        if use_audio:
            try:
                subprocess.run(
                    [
                        "ffmpeg", "-y",
                        "-i", str(write_path),
                        "-i", str(audio_source_path),
                        "-c:v", "copy",
                        "-c:a", "aac",
                        "-shortest",
                        str(final_output),
                    ],
                    capture_output=True,
                    timeout=300,
                    check=True,
                )
            finally:
                if write_path.exists():
                    write_path.unlink()
