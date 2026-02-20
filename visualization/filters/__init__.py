"""Filter registry and filter implementations."""

from .base import BaseFilter
from .difference_heatmap import DifferenceHeatmapFilter


class FilterRegistry:
    """Registry of available video visualization filters."""

    _filters: dict[str, type[BaseFilter]] = {}

    @classmethod
    def register(cls, filter_cls: type[BaseFilter]) -> type[BaseFilter]:
        """Register a filter class. Can be used as a decorator."""
        cls._filters[filter_cls.name] = filter_cls
        return filter_cls

    @classmethod
    def get_filter_names(cls) -> list[str]:
        """Return all registered filter names."""
        return list(cls._filters.keys())

    @classmethod
    def create_filter(cls, name: str) -> BaseFilter:
        """Instantiate and return a filter by name."""
        if name not in cls._filters:
            raise KeyError(f"Unknown filter: {name}")
        return cls._filters[name]()


# Auto-register built-in filters
FilterRegistry.register(DifferenceHeatmapFilter)
