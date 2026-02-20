"""Main window for the video visualization & comparison tool."""

import logging
import math
import time
from pathlib import Path

from PySide6.QtCore import QElapsedTimer, QPoint, QTimer, Qt
from PySide6.QtGui import QAction, QKeyEvent
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QSlider,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from visualization.core.audio_player import AudioPlayer
from visualization.core.exporter import Exporter
from visualization.core.video_manager import FrameCache, VideoManager
from visualization.ui.context_menu import VideoContextMenu
from visualization.ui.export_dialog import ExportDialog
from visualization.ui.filter_dialog import FilterDialog
from visualization.ui.video_canvas import VideoCanvas

logger = logging.getLogger(__name__)

_VIDEO_EXTENSIONS = "Video Files (*.mp4 *.avi *.mkv *.mov *.webm);;All Files (*)"


class MainWindow(QMainWindow):
    """Top-level window: menu bar, video canvas, transport controls, status bar."""

    def __init__(
        self,
        video_manager: VideoManager | None = None,
        frame_cache: FrameCache | None = None,
        audio_player: AudioPlayer | None = None,
        rows: int = 1,
    ) -> None:
        super().__init__()
        self.setWindowTitle("Video Visualizer")
        self.setMinimumSize(640, 480)
        self.resize(1280, 720)
        self.setAcceptDrops(True)

        self._video_manager = video_manager or VideoManager()
        self._frame_cache = frame_cache or FrameCache()
        self._audio_player = audio_player or AudioPlayer()
        self._rows = rows
        self._playing = False
        self._playback_speed = 1.0
        self._playback_start_time: float = 0.0
        self._playback_start_frame: int = 0

        self._playback_timer = QTimer(self)
        self._playback_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._playback_timer.timeout.connect(self._on_playback_tick)

        self._setup_menu()
        self._setup_central()
        self._setup_statusbar()
        self._after_videos_changed()

    # ── Menu ──────────────────────────────────────────────────────────

    def _setup_menu(self) -> None:
        menu_bar = self.menuBar()

        file_menu = menu_bar.addMenu("File")
        load_action = QAction("Load Videos", self)
        load_action.triggered.connect(self._on_load_videos)
        file_menu.addAction(load_action)

        view_menu = menu_bar.addMenu("View")
        clear_action = QAction("Clear Videos", self)
        clear_action.triggered.connect(self._on_clear_videos)
        view_menu.addAction(clear_action)

        view_menu.addSeparator()
        rows_menu = view_menu.addMenu("Set Rows")
        for n in (1, 2, 3, 4):
            action = QAction(f"{n} row{'s' if n > 1 else ''}", self)
            action.triggered.connect(lambda checked=False, r=n: self._set_rows(r))
            rows_menu.addAction(action)

        export_action = QAction("Export", self)
        export_action.triggered.connect(self._on_export)
        menu_bar.addAction(export_action)

        self._export_action = export_action

    # ── Central widget ────────────────────────────────────────────────

    def _setup_central(self) -> None:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)

        self._canvas = VideoCanvas(self._video_manager, self._frame_cache)
        self._canvas.set_rows(self._rows)
        self._canvas.context_menu_requested.connect(self._on_context_menu)
        layout.addWidget(self._canvas, stretch=1)

        transport = QHBoxLayout()
        transport.setContentsMargins(4, 2, 4, 2)

        self._play_btn = QPushButton("▶")
        self._play_btn.setFixedWidth(32)
        self._play_btn.clicked.connect(self._toggle_playback)
        transport.addWidget(self._play_btn)

        self._speed_spin = QDoubleSpinBox()
        self._speed_spin.setRange(0.1, 10.0)
        self._speed_spin.setSingleStep(0.25)
        self._speed_spin.setValue(1.0)
        self._speed_spin.setSuffix("x")
        self._speed_spin.setDecimals(2)
        self._speed_spin.setMinimumWidth(90)
        self._speed_spin.setStyleSheet("QDoubleSpinBox { font-size: 13px; }")
        self._speed_spin.valueChanged.connect(self._on_speed_changed)
        transport.addWidget(self._speed_spin)

        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setMinimum(0)
        self._slider.setMaximum(0)
        self._slider.valueChanged.connect(self._on_slider_changed)
        transport.addWidget(self._slider, stretch=1)

        layout.addLayout(transport)
        self.setCentralWidget(container)

    # ── Status bar ────────────────────────────────────────────────────

    def _setup_statusbar(self) -> None:
        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self._frame_label = QLabel("Frame: 0 / 0")
        self._time_label = QLabel("Time: 00:00.000")
        self._status_bar.addWidget(self._frame_label)
        self._status_bar.addWidget(self._time_label)

    # ── Video loading ─────────────────────────────────────────────────

    def load_videos(self, paths: list[str | Path]) -> None:
        """Load one or more video files. Called from menu, drag-drop, or CLI."""
        for p in paths:
            try:
                self._video_manager.load_video(p)
            except ValueError as e:
                QMessageBox.warning(self, "Framerate mismatch", str(e))
            except (FileNotFoundError, RuntimeError) as e:
                QMessageBox.warning(self, "Cannot open video", str(e))

        self._after_videos_changed()

    def _on_load_videos(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Load Videos", "", _VIDEO_EXTENSIONS
        )
        if paths:
            self.load_videos(paths)

    def _on_clear_videos(self) -> None:
        self._stop_playback()
        self._video_manager.clear()
        self._frame_cache.clear()
        self._audio_player.clear()
        self._after_videos_changed()

    def _after_videos_changed(self) -> None:
        max_frames = self._video_manager.max_frame_count
        self._slider.setMaximum(max(0, max_frames - 1))
        self._slider.setValue(0)
        self._canvas.set_frame(0)
        self._update_status(0)
        self._update_controls_state()
        self._setup_default_audio()

    def _setup_default_audio(self) -> None:
        """Set audio source to video 0 if it has audio."""
        v0 = self._video_manager.get_video(0)
        if v0 and v0.info.has_audio:
            self._audio_player.set_source(v0.info.path, v0.info.fps)

    def _update_controls_state(self) -> None:
        has_videos = self._video_manager.video_count > 0
        self._slider.setEnabled(has_videos)
        self._play_btn.setEnabled(has_videos)
        self._export_action.setEnabled(has_videos)

    # ── Scrubbing & playback ──────────────────────────────────────────

    def _on_slider_changed(self, value: int) -> None:
        if not self._playing:
            self._canvas.set_frame(value)
            self._update_status(value)
            self._audio_player.play_snippet(value)

    def _toggle_playback(self) -> None:
        if self._playing:
            self._stop_playback()
        else:
            self._start_playback()

    def _start_playback(self) -> None:
        fps = self._video_manager.session_fps
        if fps is None or fps <= 0:
            return
        self._playing = True
        self._play_btn.setText("⏸")
        self._playback_start_time = time.monotonic()
        self._playback_start_frame = self._slider.value()
        self._playback_timer.start(8)
        self._audio_player.play_from(self._slider.value())

    def _stop_playback(self) -> None:
        self._playing = False
        self._play_btn.setText("▶")
        self._playback_timer.stop()
        self._audio_player.stop()

    def _on_playback_tick(self) -> None:
        fps = self._video_manager.session_fps or 25.0
        elapsed = time.monotonic() - self._playback_start_time
        expected_frame = self._playback_start_frame + int(
            elapsed * fps * self._playback_speed
        )
        expected_frame = min(expected_frame, self._slider.maximum())
        if expected_frame > self._slider.maximum() - 1:
            self._slider.blockSignals(True)
            self._slider.setValue(self._slider.maximum())
            self._slider.blockSignals(False)
            self._canvas.set_frame(self._slider.maximum())
            self._update_status(self._slider.maximum())
            self._stop_playback()
            return
        if expected_frame != self._slider.value():
            self._slider.blockSignals(True)
            self._slider.setValue(expected_frame)
            self._slider.blockSignals(False)
            self._canvas.set_frame(expected_frame)
            self._update_status(expected_frame)

    def _on_speed_changed(self, value: float) -> None:
        if self._playing:
            current = self._slider.value()
            self._playback_start_time = time.monotonic()
            self._playback_start_frame = current
            self._audio_player.stop()
            self._audio_player.play_from(current)
        self._playback_speed = value

    # ── Keyboard navigation ───────────────────────────────────────────

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Left:
            self._slider.setValue(max(0, self._slider.value() - 1))
        elif event.key() == Qt.Key.Key_Right:
            self._slider.setValue(
                min(self._slider.maximum(), self._slider.value() + 1)
            )
        else:
            super().keyPressEvent(event)

    # ── Drag and drop ─────────────────────────────────────────────────

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.load_videos(paths)

    # ── Context menu ──────────────────────────────────────────────────

    def _on_context_menu(self, video_id: int, pos: QPoint) -> None:
        entry = self._video_manager.get_video(video_id)
        if entry is None:
            return
        menu = VideoContextMenu(entry, self._video_manager, self)
        menu.caption_changed.connect(lambda vid, txt: self._canvas.update())
        menu.filter_requested.connect(self._on_filter_requested)
        menu.filter_cleared.connect(self._on_filter_cleared)
        menu.filter_cleared_all.connect(self._on_filter_cleared_all)
        menu.zoom_reset_requested.connect(self._canvas.reset_roi)
        menu.audio_source_changed.connect(self._on_audio_source_changed)
        menu.exec(pos)

    def _on_filter_requested(self, video_id: int) -> None:
        entry = self._video_manager.get_video(video_id)
        if entry is None:
            return
        dlg = FilterDialog(entry, self._video_manager, self)
        if dlg.exec():
            self._frame_cache.clear(video_id)
            if dlg.apply_to_all and dlg.selected_filter_name != "None":
                from visualization.filters import FilterRegistry

                ref_id = dlg.selected_ref_id
                for v in self._video_manager.get_all_videos():
                    if v.video_id == entry.video_id:
                        continue
                    if ref_id is not None and v.video_id == ref_id:
                        v.filter = None
                        continue
                    flt = FilterRegistry.create_filter(dlg.selected_filter_name)
                    if flt.needs_reference and ref_id is not None:
                        flt.ref_video_id = ref_id
                    v.filter = flt
                    self._frame_cache.clear(v.video_id)
            self._canvas.update()

    def _on_filter_cleared(self, video_id: int) -> None:
        self._frame_cache.clear(video_id)
        self._canvas.update()

    def _on_filter_cleared_all(self) -> None:
        self._frame_cache.clear()
        self._canvas.update()

    def _on_audio_source_changed(self, video_id: int) -> None:
        entry = self._video_manager.get_video(video_id)
        if entry is None:
            return
        self._audio_player.set_source(entry.info.path, entry.info.fps)

    # ── Export ─────────────────────────────────────────────────────────

    def _on_export(self) -> None:
        if self._video_manager.video_count == 0:
            return
        dlg = ExportDialog(self._video_manager, self)
        if not dlg.exec():
            return
        if not dlg.output_path:
            QMessageBox.warning(self, "Export", "No output path specified.")
            return

        self._stop_playback()
        exporter = Exporter(self._video_manager, self._frame_cache)
        total = self._video_manager.max_frame_count

        progress = QProgressDialog("Exporting video...", "Cancel", 0, total, self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        cancelled = False

        def on_progress(frame_idx: int, total_frames: int) -> None:
            nonlocal cancelled
            progress.setValue(frame_idx + 1)
            if progress.wasCanceled():
                cancelled = True
                raise InterruptedError("Export cancelled by user.")

        audio_path = self._audio_player._source_path
        try:
            exporter.export(
                output_path=dlg.output_path,
                export_width=dlg.export_width,
                export_height=dlg.export_height,
                audio_source_path=audio_path,
                rows=self._rows,
                roi=self._canvas.roi,
                progress_callback=on_progress,
            )
            progress.close()
            if not cancelled:
                QMessageBox.information(
                    self, "Export", f"Export complete:\n{dlg.output_path}"
                )
        except InterruptedError:
            progress.close()
        except Exception as e:
            progress.close()
            QMessageBox.critical(self, "Export failed", str(e))

    # ── Rows ──────────────────────────────────────────────────────────

    def _set_rows(self, rows: int) -> None:
        self._rows = rows
        self._canvas.set_rows(rows)

    # ── Status bar update ─────────────────────────────────────────────

    def _update_status(self, frame_idx: int) -> None:
        total = self._video_manager.max_frame_count
        fps = self._video_manager.session_fps or 25.0
        t_sec = frame_idx / fps
        minutes = int(t_sec) // 60
        seconds = t_sec - minutes * 60
        self._frame_label.setText(f"Frame: {frame_idx} / {total}")
        self._time_label.setText(f"Time: {minutes:02d}:{seconds:06.3f}")

    # ── Cleanup ───────────────────────────────────────────────────────

    def closeEvent(self, event) -> None:
        self._stop_playback()
        self._audio_player.cleanup()
        self._video_manager.clear()
        super().closeEvent(event)
