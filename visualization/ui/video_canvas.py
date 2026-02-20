"""Video canvas widget for rendering video panels in a grid layout."""

import math
from typing import TYPE_CHECKING

import cv2
import numpy as np
from PySide6.QtCore import QPoint, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QImage, QMouseEvent, QPainter, QPen, QWheelEvent
from PySide6.QtWidgets import QWidget

from visualization.core.video_manager import FrameCache, VideoManager

if TYPE_CHECKING:
    from visualization.core.video_manager import VideoEntry


class VideoCanvas(QWidget):
    """Widget that renders all video panels in a grid layout.

    Supports right-click context menus and left-drag ROI zoom.
    """

    context_menu_requested = Signal(int, QPoint)

    def __init__(
        self,
        video_manager: VideoManager,
        frame_cache: FrameCache,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._video_manager = video_manager
        self._frame_cache = frame_cache
        self._current_frame: int = 0
        self._rows: int = 1

        # ROI in normalised original-frame coordinates (x1, y1, x2, y2)
        self._roi: tuple[float, float, float, float] | None = None

        # Drag state for drawing a selection rectangle (left button)
        self._drag_start: QPoint | None = None
        self._drag_current: QPoint | None = None
        self._drag_panel_idx: int | None = None

        # Pan state (middle button)
        self._pan_last: QPoint | None = None
        self._pan_panel_idx: int | None = None

        self.setMouseTracking(False)
        self.setFocusPolicy(Qt.StrongFocus)

    # ── Public API ────────────────────────────────────────────────────

    def set_frame(self, frame_idx: int) -> None:
        self._current_frame = frame_idx
        self.update()

    def set_rows(self, rows: int) -> None:
        self._rows = max(1, rows)
        self.update()

    def reset_roi(self) -> None:
        """Clear the zoom region and show the full frame."""
        self._roi = None
        self.update()

    @property
    def roi(self) -> tuple[float, float, float, float] | None:
        return self._roi

    # ── Grid geometry helpers ─────────────────────────────────────────

    def _grid_cols(self, count: int) -> int:
        return math.ceil(count / self._rows) if self._rows > 0 else 1

    def _get_panel_rect(self, video_index: int) -> QRect:
        videos = self._video_manager.get_all_videos()
        if video_index < 0 or video_index >= len(videos):
            return QRect()
        count = len(videos)
        cols = self._grid_cols(count)
        w = self.width() // cols
        h = self.height() // self._rows
        col = video_index % cols
        row = video_index // cols
        return QRect(col * w, row * h, w, h)

    def _panel_index_at(self, pos: QPoint) -> int | None:
        """Return the video-list index whose panel contains *pos*, or None."""
        videos = self._video_manager.get_all_videos()
        for idx in range(len(videos)):
            if self._get_panel_rect(idx).contains(pos):
                return idx
        return None

    def _content_rect_in_panel(self, panel_rect: QRect, frame_w: int, frame_h: int) -> QRectF:
        """Return the sub-rect inside *panel_rect* that the frame content occupies
        after aspect-ratio-preserving letterbox resize."""
        pw, ph = panel_rect.width(), panel_rect.height()
        if frame_w <= 0 or frame_h <= 0 or pw <= 0 or ph <= 0:
            return QRectF(panel_rect)
        scale = min(pw / frame_w, ph / frame_h)
        cw = frame_w * scale
        ch = frame_h * scale
        cx = panel_rect.x() + (pw - cw) / 2
        cy = panel_rect.y() + (ph - ch) / 2
        return QRectF(cx, cy, cw, ch)

    # ── Coordinate mapping (screen ↔ normalised frame) ────────────────

    def _screen_to_norm(self, pos: QPoint, panel_rect: QRect, frame_w: int, frame_h: int) -> tuple[float, float]:
        """Map a widget-coordinate point to normalised [0,1] coordinates of
        the *visible* frame region (i.e. after ROI crop)."""
        cr = self._content_rect_in_panel(panel_rect, frame_w, frame_h)
        nx = max(0.0, min(1.0, (pos.x() - cr.x()) / cr.width())) if cr.width() > 0 else 0.0
        ny = max(0.0, min(1.0, (pos.y() - cr.y()) / cr.height())) if cr.height() > 0 else 0.0
        return (nx, ny)

    def _visible_to_abs(self, nx: float, ny: float) -> tuple[float, float]:
        """Convert normalised coordinates in the *visible* (possibly cropped)
        frame to normalised coordinates in the original full frame."""
        if self._roi is None:
            return (nx, ny)
        x1, y1, x2, y2 = self._roi
        return (x1 + nx * (x2 - x1), y1 + ny * (y2 - y1))

    # ── Frame cropping ────────────────────────────────────────────────

    def _crop_to_roi(self, frame: np.ndarray) -> np.ndarray:
        """Crop *frame* to the current ROI (if set)."""
        if self._roi is None:
            return frame
        h, w = frame.shape[:2]
        x1, y1, x2, y2 = self._roi
        cx1 = max(0, int(x1 * w))
        cy1 = max(0, int(y1 * h))
        cx2 = min(w, int(x2 * w))
        cy2 = min(h, int(y2 * h))
        if cx2 <= cx1 or cy2 <= cy1:
            return frame
        return frame[cy1:cy2, cx1:cx2]

    # ── Paint ─────────────────────────────────────────────────────────

    def paintEvent(self, event: object) -> None:
        videos = self._video_manager.get_all_videos()
        if not videos:
            painter = QPainter(self)
            painter.setPen(painter.pen().color())
            painter.drawText(
                self.rect(),
                Qt.AlignmentFlag.AlignCenter,
                "Drag & drop videos here or use File → Load Videos",
            )
            return

        count = len(videos)
        cols = self._grid_cols(count)
        panel_w = self.width() // cols
        panel_h = self.height() // self._rows

        painter = QPainter(self)
        for idx, video in enumerate(videos):
            rect = self._get_panel_rect(idx)
            if rect.isEmpty():
                continue

            frame = self._frame_cache.get(video.video_id, self._current_frame)
            if frame is None:
                frame = video.read_frame(self._current_frame)
                if frame is not None:
                    self._frame_cache.put(video.video_id, self._current_frame, frame)

            if frame is not None:
                frame = self._crop_to_roi(frame)

            if frame is not None and video.filter is not None:
                ref_frame = None
                if video.filter.needs_reference and hasattr(video.filter, "ref_video_id"):
                    ref_id = video.filter.ref_video_id
                    if ref_id is not None:
                        ref_entry = self._video_manager.get_video(ref_id)
                        if ref_entry is not None:
                            ref_frame = self._frame_cache.get(ref_id, self._current_frame)
                            if ref_frame is None:
                                ref_frame = ref_entry.read_frame(self._current_frame)
                                if ref_frame is not None:
                                    self._frame_cache.put(ref_id, self._current_frame, ref_frame)
                            if ref_frame is not None:
                                ref_frame = self._crop_to_roi(ref_frame)
                frame = video.filter.apply(frame, ref_frame)

            if frame is not None:
                frame = self._resize_letterbox(frame, panel_w, panel_h)
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                h, w = rgb.shape[:2]
                bpl = w * 3
                qimg = QImage(rgb.data, w, h, bpl, QImage.Format.Format_RGB888).copy()
                painter.drawImage(rect.topLeft(), qimg)

            # Label
            label = video.label
            font = painter.font()
            px = max(10, panel_h // 20)
            font.setPixelSize(px)
            fm = QFontMetrics(font)
            margin = 8
            while fm.horizontalAdvance(label) > panel_w - margin and px > 8:
                px -= 1
                font.setPixelSize(px)
                fm = QFontMetrics(font)
            painter.setFont(font)
            flags = Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter
            painter.setPen(Qt.GlobalColor.black)
            for dx, dy in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
                painter.drawText(rect.adjusted(dx, dy, dx, dy), flags, label)
            painter.setPen(Qt.GlobalColor.white)
            painter.drawText(rect, flags, label)

        # Draw rubber-band selection rectangle while dragging
        if self._drag_start is not None and self._drag_current is not None:
            sel = QRect(self._drag_start, self._drag_current).normalized()
            painter.setPen(QPen(QColor(255, 255, 0), 2, Qt.PenStyle.DashLine))
            painter.setBrush(QColor(255, 255, 0, 40))
            painter.drawRect(sel)

    # ── Letterbox resize ──────────────────────────────────────────────

    def _resize_letterbox(self, frame: np.ndarray, target_w: int, target_h: int) -> np.ndarray:
        h, w = frame.shape[:2]
        if w <= 0 or h <= 0 or target_w <= 0 or target_h <= 0:
            return frame
        scale = min(target_w / w, target_h / h)
        new_w = max(1, int(w * scale))
        new_h = max(1, int(h * scale))
        resized = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
        pad_w = target_w - new_w
        pad_h = target_h - new_h
        top = pad_h // 2
        bottom = pad_h - top
        left = pad_w // 2
        right = pad_w - left
        return cv2.copyMakeBorder(resized, top, bottom, left, right, cv2.BORDER_CONSTANT, value=(0, 0, 0))

    # ── Mouse events ──────────────────────────────────────────────────

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            idx = self._panel_index_at(event.position().toPoint())
            if idx is not None:
                self._drag_panel_idx = idx
                self._drag_start = event.position().toPoint()
                self._drag_current = self._drag_start
            event.accept()
        elif event.button() == Qt.MouseButton.MiddleButton:
            if self._roi is not None:
                idx = self._panel_index_at(event.position().toPoint())
                if idx is not None:
                    self._pan_panel_idx = idx
                    self._pan_last = event.position().toPoint()
            event.accept()
        elif event.button() == Qt.MouseButton.RightButton:
            videos = self._video_manager.get_all_videos()
            pos = event.position().toPoint()
            for idx in range(len(videos)):
                if self._get_panel_rect(idx).contains(pos):
                    self.context_menu_requested.emit(
                        videos[idx].video_id,
                        self.mapToGlobal(pos),
                    )
                    return
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._pan_last is not None:
            self._apply_pan(event.position().toPoint())
            event.accept()
        elif self._drag_start is not None:
            self._drag_current = event.position().toPoint()
            self.update()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.MiddleButton and self._pan_last is not None:
            self._pan_last = None
            self._pan_panel_idx = None
            event.accept()
        elif event.button() == Qt.MouseButton.LeftButton and self._drag_start is not None:
            end = event.position().toPoint()
            self._finalize_roi(self._drag_start, end)
            self._drag_start = None
            self._drag_current = None
            self._drag_panel_idx = None
            self.update()
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.reset_roi()
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        delta = event.angleDelta().y()
        if delta == 0:
            super().wheelEvent(event)
            return

        idx = self._panel_index_at(event.position().toPoint())
        if idx is None:
            super().wheelEvent(event)
            return

        videos = self._video_manager.get_all_videos()
        if idx >= len(videos):
            super().wheelEvent(event)
            return

        video = videos[idx]
        panel_rect = self._get_panel_rect(idx)

        if self._roi is not None:
            rx1, ry1, rx2, ry2 = self._roi
            fw = max(1, int((rx2 - rx1) * video.info.width))
            fh = max(1, int((ry2 - ry1) * video.info.height))
        else:
            fw, fh = video.info.width, video.info.height

        vn = self._screen_to_norm(event.position().toPoint(), panel_rect, fw, fh)
        ax, ay = self._visible_to_abs(vn[0], vn[1])

        # Smooth zoom: 0.85 per notch (120 units), supporting fractional notches
        _ZOOM_BASE = 0.85
        steps = delta / 120.0
        factor = _ZOOM_BASE ** steps

        x1, y1, x2, y2 = self._roi if self._roi is not None else (0.0, 0.0, 1.0, 1.0)
        w = x2 - x1
        h = y2 - y1

        new_w = w * factor
        new_h = h * factor

        if new_w >= 1.0 and new_h >= 1.0:
            self._roi = None
            self.update()
            event.accept()
            return

        # Anchor: keep the point under the cursor stationary
        rel_x = (ax - x1) / w if w > 0 else 0.5
        rel_y = (ay - y1) / h if h > 0 else 0.5

        new_x1 = ax - rel_x * new_w
        new_y1 = ay - rel_y * new_h
        new_x2 = new_x1 + new_w
        new_y2 = new_y1 + new_h

        # Shift (not squeeze) to keep within [0, 1]
        if new_x1 < 0:
            new_x2 -= new_x1
            new_x1 = 0.0
        if new_y1 < 0:
            new_y2 -= new_y1
            new_y1 = 0.0
        if new_x2 > 1.0:
            new_x1 -= new_x2 - 1.0
            new_x2 = 1.0
        if new_y2 > 1.0:
            new_y1 -= new_y2 - 1.0
            new_y2 = 1.0

        new_x1 = max(0.0, new_x1)
        new_y1 = max(0.0, new_y1)
        new_x2 = min(1.0, new_x2)
        new_y2 = min(1.0, new_y2)

        if new_x2 - new_x1 >= 0.999 and new_y2 - new_y1 >= 0.999:
            self._roi = None
        else:
            self._roi = (new_x1, new_y1, new_x2, new_y2)

        self.update()
        event.accept()

    def _finalize_roi(self, start: QPoint, end: QPoint) -> None:
        """Compute the ROI in normalised original-frame coordinates from the
        drag rectangle and apply it."""
        if self._drag_panel_idx is None:
            return
        videos = self._video_manager.get_all_videos()
        if self._drag_panel_idx >= len(videos):
            return
        video = videos[self._drag_panel_idx]
        panel_rect = self._get_panel_rect(self._drag_panel_idx)

        # Determine the dimensions of the frame that was actually rendered
        # (after ROI crop if one is active).
        if self._roi is not None:
            x1, y1, x2, y2 = self._roi
            fw = max(1, int((x2 - x1) * video.info.width))
            fh = max(1, int((y2 - y1) * video.info.height))
        else:
            fw, fh = video.info.width, video.info.height

        n1 = self._screen_to_norm(start, panel_rect, fw, fh)
        n2 = self._screen_to_norm(end, panel_rect, fw, fh)

        nx1 = min(n1[0], n2[0])
        ny1 = min(n1[1], n2[1])
        nx2 = max(n1[0], n2[0])
        ny2 = max(n1[1], n2[1])

        # Ignore tiny accidental clicks (< 2 % of frame in either dimension)
        if (nx2 - nx1) < 0.02 or (ny2 - ny1) < 0.02:
            return

        # Convert from visible-region-relative to absolute frame coords
        ax1, ay1 = self._visible_to_abs(nx1, ny1)
        ax2, ay2 = self._visible_to_abs(nx2, ny2)

        self._roi = (
            max(0.0, min(1.0, ax1)),
            max(0.0, min(1.0, ay1)),
            max(0.0, min(1.0, ax2)),
            max(0.0, min(1.0, ay2)),
        )

    def _apply_pan(self, pos: QPoint) -> None:
        """Shift the ROI by the screen-space delta between *pos* and the last
        recorded pan position.  Only active when an ROI is set."""
        if self._roi is None or self._pan_last is None or self._pan_panel_idx is None:
            return

        videos = self._video_manager.get_all_videos()
        if self._pan_panel_idx >= len(videos):
            return
        video = videos[self._pan_panel_idx]
        panel_rect = self._get_panel_rect(self._pan_panel_idx)

        x1, y1, x2, y2 = self._roi
        fw = max(1, int((x2 - x1) * video.info.width))
        fh = max(1, int((y2 - y1) * video.info.height))

        cr = self._content_rect_in_panel(panel_rect, fw, fh)
        if cr.width() <= 0 or cr.height() <= 0:
            return

        roi_w = x2 - x1
        roi_h = y2 - y1
        dx_norm = -((pos.x() - self._pan_last.x()) / cr.width()) * roi_w
        dy_norm = -((pos.y() - self._pan_last.y()) / cr.height()) * roi_h

        new_x1 = x1 + dx_norm
        new_y1 = y1 + dy_norm
        new_x2 = x2 + dx_norm
        new_y2 = y2 + dy_norm

        # Clamp by shifting, not squeezing
        if new_x1 < 0:
            new_x2 -= new_x1
            new_x1 = 0.0
        if new_y1 < 0:
            new_y2 -= new_y1
            new_y1 = 0.0
        if new_x2 > 1.0:
            new_x1 -= new_x2 - 1.0
            new_x2 = 1.0
        if new_y2 > 1.0:
            new_y1 -= new_y2 - 1.0
            new_y2 = 1.0

        self._roi = (
            max(0.0, new_x1), max(0.0, new_y1),
            min(1.0, new_x2), min(1.0, new_y2),
        )
        self._pan_last = pos
        self.update()
