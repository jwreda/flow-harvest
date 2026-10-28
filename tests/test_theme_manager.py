"""
Tests for ThemeManager and SettingsManager.
"""

import pytest
from PyQt5.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    """Create QApplication instance for tests."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


class TestThemeManager:
    """Tests for ThemeManager class."""

    def test_theme_manager_singleton(self, qapp):
        """Test that ThemeManager is a singleton."""
        from flowkit_gui.utils.theme_manager import ThemeManager, get_theme_manager

        manager1 = ThemeManager.instance()
        manager2 = ThemeManager.instance()
        manager3 = get_theme_manager()

        assert manager1 is manager2
        assert manager2 is manager3

    def test_default_mode_is_system(self, qapp):
        """Test that default theme mode is SYSTEM."""
        from flowkit_gui.utils.theme_manager import ThemeManager, ThemeMode

        # Create fresh instance for test
        manager = ThemeManager()
        assert manager.mode == ThemeMode.SYSTEM

    def test_set_light_mode(self, qapp):
        """Test setting light theme mode."""
        from flowkit_gui.utils.theme_manager import ThemeManager, ThemeMode

        manager = ThemeManager()
        manager.set_mode(ThemeMode.LIGHT)

        assert manager.mode == ThemeMode.LIGHT
        assert manager.get_actual_theme() == "light"
        assert manager.is_light()
        assert not manager.is_dark()

    def test_set_dark_mode(self, qapp):
        """Test setting dark theme mode."""
        from flowkit_gui.utils.theme_manager import ThemeManager, ThemeMode

        manager = ThemeManager()
        manager.set_mode(ThemeMode.DARK)

        assert manager.mode == ThemeMode.DARK
        assert manager.get_actual_theme() == "dark"
        assert manager.is_dark()
        assert not manager.is_light()

    def test_cycle_mode(self, qapp):
        """Test cycling through theme modes."""
        from flowkit_gui.utils.theme_manager import ThemeManager, ThemeMode

        manager = ThemeManager()

        # Start with SYSTEM
        manager.set_mode(ThemeMode.SYSTEM)
        assert manager.mode == ThemeMode.SYSTEM

        # Cycle to LIGHT
        manager.cycle_mode()
        assert manager.mode == ThemeMode.LIGHT

        # Cycle to DARK
        manager.cycle_mode()
        assert manager.mode == ThemeMode.DARK

        # Cycle back to SYSTEM
        manager.cycle_mode()
        assert manager.mode == ThemeMode.SYSTEM

    def test_theme_changed_signal(self, qapp):
        """Test that theme_changed signal is emitted."""
        from flowkit_gui.utils.theme_manager import ThemeManager, ThemeMode

        manager = ThemeManager()
        received_themes = []

        def on_theme_changed(theme):
            received_themes.append(theme)

        manager.theme_changed.connect(on_theme_changed)

        # Start from known state (LIGHT), then switch to DARK
        # This ensures deterministic behavior regardless of system dark mode setting
        manager.set_mode(ThemeMode.LIGHT)
        received_themes.clear()  # Clear any signal from initial set
        manager.set_mode(ThemeMode.DARK)

        assert "dark" in received_themes


class TestSettingsManager:
    """Tests for SettingsManager class."""

    def test_settings_manager_singleton(self, qapp):
        """Test that SettingsManager is a singleton."""
        from flowkit_gui.utils.settings_manager import SettingsManager, get_settings

        manager1 = SettingsManager.instance()
        manager2 = SettingsManager.instance()
        manager3 = get_settings()

        assert manager1 is manager2
        assert manager2 is manager3

    def test_theme_mode_persistence(self, qapp):
        """Test that theme mode can be saved and loaded."""
        from flowkit_gui.utils.settings_manager import SettingsManager
        from flowkit_gui.utils.theme_manager import ThemeMode

        manager = SettingsManager()

        # Save dark mode
        manager.set_theme_mode(ThemeMode.DARK)

        # Create new instance and verify
        manager2 = SettingsManager()
        assert manager2.get_theme_mode() == ThemeMode.DARK

        # Clean up - restore system mode
        manager.set_theme_mode(ThemeMode.SYSTEM)

    def test_recent_files(self, qapp):
        """Test recent files management."""
        from flowkit_gui.utils.settings_manager import SettingsManager

        manager = SettingsManager()

        # Clear existing files
        manager.clear_recent_files()
        assert manager.get_recent_files() == []

        # Add files
        manager.add_recent_file("/path/to/file1.wsp")
        manager.add_recent_file("/path/to/file2.wsp")

        files = manager.get_recent_files()
        assert len(files) >= 2
        # Most recent should be first
        assert "file2.wsp" in files[0]

        # Clean up
        manager.clear_recent_files()


class TestColorPalettes:
    """Tests for color palette files."""

    def test_light_colors_complete(self, qapp):
        """Test that light colors palette has all required keys."""
        from flowkit_gui.utils.colors_light import COLORS

        required_keys = [
            "primary", "primary_hover", "primary_pressed", "primary_light",
            "background", "surface", "surface_hover",
            "text_primary", "text_secondary", "text_disabled", "text_on_primary",
            "border", "border_hover", "border_focus",
            "selection", "alt_row", "hover",
            "scrollbar_handle", "scrollbar_handle_hover",
            "tooltip_bg", "tooltip_text",
        ]

        for key in required_keys:
            assert key in COLORS, f"Missing key: {key}"
            assert COLORS[key].startswith("#") or COLORS[key].startswith("rgba"), \
                f"Invalid color format for {key}: {COLORS[key]}"

    def test_dark_colors_complete(self, qapp):
        """Test that dark colors palette has all required keys."""
        from flowkit_gui.utils.colors_dark import COLORS

        required_keys = [
            "primary", "primary_hover", "primary_pressed", "primary_light",
            "background", "surface", "surface_hover",
            "text_primary", "text_secondary", "text_disabled", "text_on_primary",
            "border", "border_hover", "border_focus",
            "selection", "alt_row", "hover",
            "scrollbar_handle", "scrollbar_handle_hover",
            "tooltip_bg", "tooltip_text",
        ]

        for key in required_keys:
            assert key in COLORS, f"Missing key: {key}"
            assert COLORS[key].startswith("#") or COLORS[key].startswith("rgba"), \
                f"Invalid color format for {key}: {COLORS[key]}"

    def test_palettes_have_same_keys(self, qapp):
        """Test that both palettes have the same keys."""
        from flowkit_gui.utils.colors_light import COLORS as LIGHT
        from flowkit_gui.utils.colors_dark import COLORS as DARK

        assert set(LIGHT.keys()) == set(DARK.keys())


class TestThemeUtilities:
    """Tests for theme utility functions."""

    def test_generate_stylesheet(self, qapp):
        """Test stylesheet generation."""
        from flowkit_gui.utils.theme import generate_stylesheet

        light_sheet = generate_stylesheet("light")
        dark_sheet = generate_stylesheet("dark")

        # Both should produce non-empty strings
        assert len(light_sheet) > 0
        assert len(dark_sheet) > 0

        # Light should have white background
        assert "#FFFFFF" in light_sheet or "#ffffff" in light_sheet.lower()

        # Dark should have dark background
        assert "#1E1E1E" in dark_sheet or "#1e1e1e" in dark_sheet.lower()

    def test_get_colors(self, qapp):
        """Test getting color dictionaries."""
        from flowkit_gui.utils.theme import get_colors

        light_colors = get_colors("light")
        dark_colors = get_colors("dark")

        assert light_colors["background"] == "#FFFFFF"
        assert dark_colors["background"] == "#1E1E1E"

    def test_get_resources_path(self, qapp):
        """Test resources path resolution."""
        from flowkit_gui.utils.theme import get_resources_path

        path = get_resources_path()
        assert path.exists()
        assert (path / "styles").exists()
        assert (path / "icons").exists()
