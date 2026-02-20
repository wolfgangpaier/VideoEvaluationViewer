"""Difference heatmap filter for visualizing pixel differences between frames."""

import cv2
import numpy as np
from PySide6.QtWidgets import QComboBox, QFormLayout, QWidget

from .base import BaseFilter

COLORMAP_OPTIONS = [
    ("JET", cv2.COLORMAP_JET),
    ("HOT", cv2.COLORMAP_HOT),
    ("INFERNO", cv2.COLORMAP_INFERNO),
]


class DifferenceHeatmapFilter(BaseFilter):
    """Filter that visualizes per-pixel difference as a heatmap."""

    name = "Difference Heatmap"
    needs_reference = True

    def __init__(self) -> None:
        self._colormap = cv2.COLORMAP_JET

    def configure(self, params: dict) -> None:
        """Apply user-supplied parameters."""
        super().configure(params)
        if "colormap" in params:
            colormap_name = params["colormap"]
            for name, constant in COLORMAP_OPTIONS:
                if name == colormap_name:
                    self._colormap = constant
                    break

    def get_config_ui(self) -> QWidget:
        """Return a widget with a QComboBox for selecting the colormap."""
        widget = QWidget()
        layout = QFormLayout(widget)

        combo = QComboBox()
        for name, _ in COLORMAP_OPTIONS:
            combo.addItem(name)
        combo.setCurrentText("JET")

        def on_colormap_changed(index: int) -> None:
            self._colormap = COLORMAP_OPTIONS[index][1]

        combo.currentIndexChanged.connect(on_colormap_changed)
        layout.addRow("Colormap:", combo)

        return widget

    def apply(
        self, frame: np.ndarray, ref_frame: np.ndarray | None = None
    ) -> np.ndarray:
        """Compute per-pixel absolute difference and apply colormap heatmap.

        If ref_frame is None, returns frame unchanged.
        """
        if ref_frame is None:
            return frame.copy()

        diff = cv2.absdiff(frame, ref_frame)
        gray_diff = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
        heatmap = cv2.applyColorMap(gray_diff, self._colormap)
        return heatmap
