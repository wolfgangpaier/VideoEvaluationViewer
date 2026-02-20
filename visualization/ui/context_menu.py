"""Context menu for video panels."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QInputDialog, QMenu

from visualization.core.video_manager import VideoEntry, VideoManager


class VideoContextMenu(QMenu):
    """Context menu for a video panel with caption, filter, and audio options."""

    filter_requested = Signal(int)
    filter_cleared = Signal(int)
    filter_cleared_all = Signal()
    zoom_reset_requested = Signal()
    audio_source_changed = Signal(int)
    caption_changed = Signal(int, str)

    def __init__(
        self,
        video_entry: VideoEntry,
        video_manager: VideoManager,
        parent: QMenu | None = None,
    ) -> None:
        super().__init__(parent)
        self._video_entry = video_entry
        self._video_manager = video_manager

        action_caption = self.addAction("Set Caption")
        action_caption.triggered.connect(self._on_set_caption)

        action_filter = self.addAction("Set Filter")
        action_filter.triggered.connect(self._on_set_filter)

        action_clear_filter = self.addAction("Clear Filter")
        action_clear_filter.triggered.connect(self._on_clear_filter)
        action_clear_filter.setEnabled(video_entry.filter is not None)

        action_clear_filter_all = self.addAction("Clear Filter (All)")
        action_clear_filter_all.triggered.connect(self._on_clear_filter_all)

        self.addSeparator()

        action_reset_zoom = self.addAction("Reset Zoom")
        action_reset_zoom.triggered.connect(lambda: self.zoom_reset_requested.emit())

        self.addSeparator()

        action_audio = self.addAction("Set Playback Audio")
        action_audio.triggered.connect(self._on_set_audio)
        action_audio.setEnabled(video_entry.info.has_audio)

    def _on_set_caption(self) -> None:
        """Open input dialog and update caption on OK."""
        text, ok = QInputDialog.getText(
            self,
            "Set Caption",
            "Caption:",
            text=self._video_entry.label,
        )
        if ok and text is not None:
            self._video_entry.label = text
            self.caption_changed.emit(self._video_entry.video_id, text)

    def _on_set_filter(self) -> None:
        """Emit filter_requested for this video."""
        self.filter_requested.emit(self._video_entry.video_id)

    def _on_clear_filter(self) -> None:
        self._video_entry.filter = None
        self.filter_cleared.emit(self._video_entry.video_id)

    def _on_clear_filter_all(self) -> None:
        for v in self._video_manager.get_all_videos():
            v.filter = None
        self.filter_cleared_all.emit()

    def _on_set_audio(self) -> None:
        """Emit audio_source_changed for this video."""
        self.audio_source_changed.emit(self._video_entry.video_id)
