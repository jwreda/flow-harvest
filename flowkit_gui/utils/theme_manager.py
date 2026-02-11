"""
Theme Manager for FlowKit GUI.

Provides centralized theme management with:
- Light/Dark/System mode support
- Signal-based theme change notifications
- System preference detection via darkdetect
"""

from enum import Enum
from typing import Optional

from PyQt5.QtCore import QObject, pyqtSignal
from PyQt5.QtGui import QPalette
from PyQt5.QtWidgets import QApplication

try:
    import darkdetect
    HAS_DARKDETECT = True
except ImportError:
    HAS_DARKDETECT = False


class ThemeMode(Enum):
    """Theme mode options."""
    LIGHT = "light"
    DARK = "dark"
    SYSTEM = "system"


class ThemeManager(QObject):
    """
    Manages application theme with light/dark mode support.

    Signals:
        theme_changed: Emitted when the actual theme changes ('light' or 'dark')
    """

    theme_changed = pyqtSignal(str)  # Emits 'light' or 'dark'

    _instance: Optional['ThemeManager'] = None

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._mode = ThemeMode.SYSTEM
        self._cached_system_theme: Optional[str] = None

        # Cache initial system theme for change detection
        self._cached_system_theme = self._get_system_theme()

        # Start system theme monitoring if available
        if HAS_DARKDETECT:
            self._start_system_monitoring()

    @classmethod
    def instance(cls) -> 'ThemeManager':
        """Get the singleton ThemeManager instance."""
        if cls._instance is None:
            cls._instance = ThemeManager()
        return cls._instance

    @property
    def mode(self) -> ThemeMode:
        """Get the current theme mode."""
        return self._mode

    def set_mode(self, mode: ThemeMode) -> None:
        """
        Set the theme mode.

        Args:
            mode: The theme mode to set (LIGHT, DARK, or SYSTEM)
        """
        old_theme = self.get_actual_theme()
        self._mode = mode
        new_theme = self.get_actual_theme()

        if old_theme != new_theme:
            self.theme_changed.emit(new_theme)

    def get_actual_theme(self) -> str:
        """
        Get the actual theme based on current mode.

        Returns:
            'light' or 'dark' based on mode and system preference
        """
        if self._mode == ThemeMode.LIGHT:
            return "light"
        elif self._mode == ThemeMode.DARK:
            return "dark"
        else:
            # System mode - detect system preference
            return self._get_system_theme()

    def _get_system_theme(self) -> str:
        """
        Detect system theme preference.

        Returns:
            'light' or 'dark' based on system settings
        """
        if HAS_DARKDETECT:
            try:
                system_theme = darkdetect.theme()
                if system_theme:
                    return system_theme.lower()
            except Exception:
                pass

        # Fallback: detect from Qt application palette
        app = QApplication.instance()
        if app:
            window_color = app.palette().color(QPalette.Window)
            if window_color.lightness() < 128:
                return "dark"

        return "light"

    def _start_system_monitoring(self) -> None:
        """Start monitoring for system theme changes."""
        if not HAS_DARKDETECT:
            return

        # Cache initial system theme
        self._cached_system_theme = self._get_system_theme()

        # Note: darkdetect.listener() is blocking, so we'd need threading
        # For now, we rely on manual detection when needed
        # A full implementation would use QTimer to periodically check

    def cycle_mode(self) -> ThemeMode:
        """
        Cycle through theme modes: System -> Light -> Dark -> System.

        Returns:
            The new theme mode
        """
        if self._mode == ThemeMode.SYSTEM:
            self.set_mode(ThemeMode.LIGHT)
        elif self._mode == ThemeMode.LIGHT:
            self.set_mode(ThemeMode.DARK)
        else:
            self.set_mode(ThemeMode.SYSTEM)

        return self._mode

    def is_dark(self) -> bool:
        """Check if the current actual theme is dark."""
        return self.get_actual_theme() == "dark"

    def is_light(self) -> bool:
        """Check if the current actual theme is light."""
        return self.get_actual_theme() == "light"

    def refresh_system_theme(self) -> None:
        """
        Refresh system theme detection and emit signal if changed.

        Call this periodically or when window gains focus to detect
        system theme changes.
        """
        if self._mode != ThemeMode.SYSTEM:
            return

        new_system_theme = self._get_system_theme()
        if new_system_theme != self._cached_system_theme:
            self._cached_system_theme = new_system_theme
            self.theme_changed.emit(new_system_theme)


# Convenience function for quick access
def get_theme_manager() -> ThemeManager:
    """Get the singleton ThemeManager instance."""
    return ThemeManager.instance()
