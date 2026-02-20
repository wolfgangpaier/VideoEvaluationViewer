"""Dialog for selecting and configuring filters for a video."""

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from visualization.core.video_manager import VideoEntry, VideoManager
from visualization.filters import FilterRegistry
from visualization.filters.base import BaseFilter


class FilterDialog(QDialog):
    """Dialog for selecting and configuring a filter for a specific video."""

    def __init__(
        self,
        video_entry: VideoEntry,
        video_manager: VideoManager,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._video_entry = video_entry
        self._video_manager = video_manager
        self._filter_instances: dict[str, BaseFilter] = {}
        self._ref_combo: QComboBox | None = None
        self._ref_widget: QWidget | None = None
        self._apply_all_cb: QCheckBox | None = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        self.setWindowTitle("Set Filter")

        top_layout = QHBoxLayout()
        self._filter_combo = QComboBox()
        self._filter_combo.addItem("None")
        for name in FilterRegistry.get_filter_names():
            self._filter_combo.addItem(name)
        self._filter_combo.currentTextChanged.connect(self._on_filter_changed)
        top_layout.addWidget(self._filter_combo)

        self._stacked = QStackedWidget()
        self._stacked.addWidget(QWidget())
        for name in FilterRegistry.get_filter_names():
            f = FilterRegistry.create_filter(name)
            self._filter_instances[name] = f
            self._stacked.addWidget(f.get_config_ui())
        top_layout.addWidget(self._stacked)
        layout.addLayout(top_layout)

        # Reference video selector — default to video 0
        self._ref_combo = QComboBox()
        default_ref_idx = 0
        for i, v in enumerate(self._video_manager.get_all_videos()):
            if v.video_id != self._video_entry.video_id:
                self._ref_combo.addItem(f"{v.video_id}: {v.label}", v.video_id)
                if v.video_id == 0:
                    default_ref_idx = self._ref_combo.count() - 1
        if self._ref_combo.count() > 0:
            self._ref_combo.setCurrentIndex(default_ref_idx)

        self._ref_widget = QWidget()
        ref_layout = QFormLayout(self._ref_widget)
        ref_layout.addRow("Reference video:", self._ref_combo)
        layout.addWidget(self._ref_widget)
        self._ref_widget.setVisible(False)

        # "Apply to all except reference" checkbox
        self._apply_all_cb = QCheckBox("Apply to all videos except the reference")
        self._apply_all_cb.setChecked(False)
        layout.addWidget(self._apply_all_cb)
        self._apply_all_cb.setVisible(False)

        # Restore state from the video's current filter
        if self._video_entry.filter is not None:
            for i, name in enumerate(FilterRegistry.get_filter_names()):
                if name == self._video_entry.filter.name:
                    self._filter_combo.setCurrentIndex(i + 1)
                    if self._video_entry.filter.needs_reference and hasattr(
                        self._video_entry.filter, "ref_video_id"
                    ):
                        ref_id = self._video_entry.filter.ref_video_id
                        for j in range(self._ref_combo.count()):
                            if self._ref_combo.itemData(j) == ref_id:
                                self._ref_combo.setCurrentIndex(j)
                                break
                    break
        self._on_filter_changed(self._filter_combo.currentText())

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_filter_changed(self, name: str) -> None:
        if name == "None" or name not in self._filter_instances:
            self._stacked.setCurrentIndex(0)
            if self._ref_widget:
                self._ref_widget.setVisible(False)
            if self._apply_all_cb:
                self._apply_all_cb.setVisible(False)
            return
        idx = FilterRegistry.get_filter_names().index(name) + 1
        self._stacked.setCurrentIndex(idx)
        needs_ref = self._filter_instances[name].needs_reference
        if self._ref_widget:
            self._ref_widget.setVisible(needs_ref)
        if self._apply_all_cb:
            self._apply_all_cb.setVisible(needs_ref)

    @property
    def apply_to_all(self) -> bool:
        """Whether the user checked 'apply to all except reference'."""
        if self._apply_all_cb is None:
            return False
        return self._apply_all_cb.isChecked()

    @property
    def selected_filter_name(self) -> str:
        """The filter name chosen in the dialog."""
        return self._filter_combo.currentText()

    @property
    def selected_ref_id(self) -> int | None:
        """The reference video ID chosen, or None."""
        if self._ref_combo is None:
            return None
        return self._ref_combo.currentData()

    def accept(self) -> None:
        """Apply selected filter to video_entry."""
        name = self._filter_combo.currentText()
        if name == "None":
            self._video_entry.filter = None
        else:
            f = self._filter_instances.get(name)
            if f is None:
                f = FilterRegistry.create_filter(name)
                self._filter_instances[name] = f
            if f.needs_reference and self._ref_combo:
                f.ref_video_id = self._ref_combo.currentData()
            self._video_entry.filter = f
        super().accept()
