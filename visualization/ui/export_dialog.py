"""Dialog for configuring and triggering video export."""

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from visualization.core.video_manager import VideoManager


class ExportDialog(QDialog):
    """Dialog for configuring and triggering video export."""

    def __init__(
        self,
        video_manager: VideoManager,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._video_manager = video_manager
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        path_layout = QHBoxLayout()
        self._path_edit = QLineEdit()
        self._path_edit.setPlaceholderText("Select output path...")
        path_layout.addWidget(self._path_edit)

        browse_btn = QPushButton("Browse")
        browse_btn.clicked.connect(self._on_browse)
        path_layout.addWidget(browse_btn)
        layout.addLayout(path_layout)

        form = QFormLayout()
        self._width_spin = QSpinBox()
        self._width_spin.setRange(0, 7680)
        self._width_spin.setValue(0)
        self._width_spin.setSpecialValueText("Auto")
        self._width_spin.valueChanged.connect(self._update_info)
        form.addRow("Export width:", self._width_spin)

        self._height_spin = QSpinBox()
        self._height_spin.setRange(0, 4320)
        self._height_spin.setValue(0)
        self._height_spin.setSpecialValueText("Auto")
        self._height_spin.valueChanged.connect(self._update_info)
        form.addRow("Export height:", self._height_spin)
        layout.addLayout(form)

        self._info_label = QLabel()
        self._update_info()
        layout.addWidget(self._info_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Export")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_browse(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Video",
            "",
            "MP4 Video (*.mp4)",
        )
        if path:
            self._path_edit.setText(path)

    def _update_info(self) -> None:
        w = self._width_spin.value() if self._width_spin else 0
        h = self._height_spin.value() if self._height_spin else 0
        max_w, max_h = self._video_manager.max_resolution
        out_w = w if w > 0 else max_w
        out_h = h if h > 0 else max_h
        self._info_label.setText(
            f"Output resolution: {out_w}×{out_h}"
            + (" (from videos)" if w == 0 or h == 0 else "")
        )

    def accept(self) -> None:
        self._output_path = self._path_edit.text().strip()
        w = self._width_spin.value()
        h = self._height_spin.value()
        self._export_width = None if w == 0 else w
        self._export_height = None if h == 0 else h
        super().accept()

    @property
    def output_path(self) -> str:
        """Output file path. Valid after accept()."""
        return getattr(self, "_output_path", "")

    @property
    def export_width(self) -> int | None:
        """Export width in pixels, or None for auto. Valid after accept()."""
        return getattr(self, "_export_width", None)

    @property
    def export_height(self) -> int | None:
        """Export height in pixels, or None for auto. Valid after accept()."""
        return getattr(self, "_export_height", None)
