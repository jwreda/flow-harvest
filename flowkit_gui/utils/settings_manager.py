"""
Settings Manager for FlowKit GUI.

Provides persistent settings storage using QSettings with:
- Theme preferences
- Recent files list
- Wizard/Advanced mode preference
- Window geometry
"""

from typing import List, Optional
from pathlib import Path

from PyQt5.QtCore import QSettings, QByteArray

from .theme_manager import ThemeMode


class SettingsManager:
    """
    Manages persistent application settings using QSettings.

    Settings are stored in:
    - macOS: ~/Library/Preferences/com.flowkit.gui.plist
    - Windows: Registry HKEY_CURRENT_USER\\Software\\FlowKit\\FlowKit GUI
    - Linux: ~/.config/FlowKit/FlowKit GUI.conf
    """

    # Settings keys
    KEY_THEME_MODE = "theme/mode"
    KEY_RECENT_FILES = "files/recent"
    KEY_MAX_RECENT_FILES = "files/max_recent"
    KEY_WIZARD_MODE = "ui/wizard_mode"
    KEY_WINDOW_GEOMETRY = "ui/window_geometry"
    KEY_WINDOW_STATE = "ui/window_state"
    KEY_SPLITTER_STATE = "ui/splitter_state"
    KEY_LAST_FCS_DIR = "files/last_fcs_dir"

    # Default values
    DEFAULT_MAX_RECENT_FILES = 10

    _instance: Optional['SettingsManager'] = None

    def __init__(self):
        self._settings = QSettings("FlowKit", "FlowKit GUI")

    @classmethod
    def instance(cls) -> 'SettingsManager':
        """Get the singleton SettingsManager instance."""
        if cls._instance is None:
            cls._instance = SettingsManager()
        return cls._instance

    # Theme settings

    def get_theme_mode(self) -> ThemeMode:
        """
        Get the saved theme mode preference.

        Returns:
            ThemeMode enum value (defaults to SYSTEM)
        """
        value = self._settings.value(self.KEY_THEME_MODE, ThemeMode.SYSTEM.value)
        try:
            return ThemeMode(value)
        except ValueError:
            return ThemeMode.SYSTEM

    def set_theme_mode(self, mode: ThemeMode) -> None:
        """
        Save the theme mode preference.

        Args:
            mode: The ThemeMode to save
        """
        self._settings.setValue(self.KEY_THEME_MODE, mode.value)

    # Recent files

    def get_recent_files(self) -> List[str]:
        """
        Get the list of recent files.

        Returns:
            List of file paths (most recent first)
        """
        files = self._settings.value(self.KEY_RECENT_FILES, [])
        if files is None:
            return []
        if isinstance(files, str):
            return [files] if files else []
        return list(files)

    def add_recent_file(self, file_path: str) -> None:
        """
        Add a file to the recent files list.

        Args:
            file_path: Path to the file to add
        """
        files = self.get_recent_files()
        # Normalize path
        file_path = str(Path(file_path).resolve())

        # Remove if already exists (will be moved to top)
        if file_path in files:
            files.remove(file_path)

        # Add to beginning
        files.insert(0, file_path)

        # Trim to max
        max_files = self._settings.value(
            self.KEY_MAX_RECENT_FILES,
            self.DEFAULT_MAX_RECENT_FILES
        )
        files = files[:int(max_files)]

        self._settings.setValue(self.KEY_RECENT_FILES, files)

    def clear_recent_files(self) -> None:
        """Clear the recent files list."""
        self._settings.setValue(self.KEY_RECENT_FILES, [])

    def remove_recent_file(self, file_path: str) -> None:
        """
        Remove a file from the recent files list.

        Args:
            file_path: Path to the file to remove
        """
        files = self.get_recent_files()
        file_path = str(Path(file_path).resolve())
        if file_path in files:
            files.remove(file_path)
            self._settings.setValue(self.KEY_RECENT_FILES, files)

    # UI mode

    def get_wizard_mode(self) -> bool:
        """
        Get wizard mode preference.

        Returns:
            True if wizard mode should be used, False for advanced mode
            Defaults to True for new installs
        """
        return self._settings.value(self.KEY_WIZARD_MODE, True, type=bool)

    def set_wizard_mode(self, enabled: bool) -> None:
        """
        Save wizard mode preference.

        Args:
            enabled: True for wizard mode, False for advanced mode
        """
        self._settings.setValue(self.KEY_WIZARD_MODE, enabled)

    # Window state

    def get_window_geometry(self) -> Optional[QByteArray]:
        """Get saved window geometry."""
        return self._settings.value(self.KEY_WINDOW_GEOMETRY)

    def set_window_geometry(self, geometry: QByteArray) -> None:
        """Save window geometry."""
        self._settings.setValue(self.KEY_WINDOW_GEOMETRY, geometry)

    def get_window_state(self) -> Optional[QByteArray]:
        """Get saved window state (toolbars, dock widgets)."""
        return self._settings.value(self.KEY_WINDOW_STATE)

    def set_window_state(self, state: QByteArray) -> None:
        """Save window state."""
        self._settings.setValue(self.KEY_WINDOW_STATE, state)

    def get_splitter_state(self) -> Optional[QByteArray]:
        """Get saved splitter state."""
        return self._settings.value(self.KEY_SPLITTER_STATE)

    def set_splitter_state(self, state: QByteArray) -> None:
        """Save splitter state."""
        self._settings.setValue(self.KEY_SPLITTER_STATE, state)

    # Directory paths

    def get_last_fcs_dir(self) -> Optional[str]:
        """Get the last used FCS directory."""
        return self._settings.value(self.KEY_LAST_FCS_DIR)

    def set_last_fcs_dir(self, directory: str) -> None:
        """Save the last used FCS directory."""
        self._settings.setValue(self.KEY_LAST_FCS_DIR, directory)

    # General settings access

    def get_value(self, key: str, default=None, value_type=None):
        """Get a setting value with optional type conversion."""
        if value_type:
            return self._settings.value(key, default, type=value_type)
        return self._settings.value(key, default)

    def set_value(self, key: str, value) -> None:
        """Set a setting value."""
        self._settings.setValue(key, value)

    def sync(self) -> None:
        """Force synchronization of settings to storage."""
        self._settings.sync()


# Convenience function for quick access
def get_settings() -> SettingsManager:
    """Get the singleton SettingsManager instance."""
    return SettingsManager.instance()
