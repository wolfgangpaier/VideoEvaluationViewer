"""Abstract base class for video visualization filters."""

from abc import ABC, abstractmethod

import numpy as np
from PySide6.QtWidgets import QWidget


class BaseFilter(ABC):
    """Abstract base class for per-video visualization filters."""

    name: str = "Base Filter"
    needs_reference: bool = False

    def configure(self, params: dict) -> None:
        """Apply user-supplied parameters.

        Args:
            params: Dictionary of parameter names to values.
        """
        pass

    def get_config_ui(self) -> QWidget:
        """Return a Qt widget for the configuration panel in the filter dialog.

        Base implementation returns an empty QWidget.
        """
        return QWidget()

    @abstractmethod
    def apply(
        self, frame: np.ndarray, ref_frame: np.ndarray | None = None
    ) -> np.ndarray:
        """Process a frame and return the result.

        Args:
            frame: Input frame as BGR uint8 numpy array (H, W, 3).
            ref_frame: Optional reference frame for filters that need it (same format).

        Returns:
            Processed frame as BGR uint8 numpy array (same shape as frame).
        """
        ...
