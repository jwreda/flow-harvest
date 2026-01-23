"""
Theme utilities for FlowKit GUI.

Provides theme loading, font management, and icon utilities for the
pink-accented modern UI theme with light/dark mode support.
"""

import sys
from pathlib import Path
from typing import Optional, Dict

from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QFont, QIcon, QPixmap, QPainter
from PyQt5.QtCore import Qt, QSize
from PyQt5.QtSvg import QSvgRenderer

from .theme_manager import ThemeManager, ThemeMode, get_theme_manager
from .settings_manager import SettingsManager, get_settings
from .colors_light import COLORS as LIGHT_COLORS
from .colors_dark import COLORS as DARK_COLORS
from .logging_config import get_logger

logger = get_logger("theme")


def get_resources_path() -> Path:
    """
    Get the path to the resources directory.

    Handles both normal execution and frozen (PyInstaller) apps.
    """
    if getattr(sys, 'frozen', False):
        # Running as compiled executable
        return Path(sys._MEIPASS) / "flowkit_gui" / "resources"
    else:
        # Running in normal Python environment
        return Path(__file__).parent.parent / "resources"


def get_app_font(size: int = 12, weight: QFont.Weight = QFont.Normal) -> QFont:
    """
    Get the application font using system fonts.

    Uses the platform's native font stack for best appearance:
    - macOS: SF Pro (via system default)
    - Windows: Segoe UI
    - Linux: System default (often Roboto or DejaVu)

    Args:
        size: Font size in points
        weight: Font weight (QFont.Normal, QFont.DemiBold, QFont.Bold)

    Returns:
        QFont configured with system font
    """
    font = QFont()
    font.setPointSize(size)
    font.setWeight(weight)
    return font


def get_colors(theme: str = None) -> Dict[str, str]:
    """
    Get the color palette for the specified or current theme.

    Args:
        theme: 'light' or 'dark'. If None, uses current theme.

    Returns:
        Dictionary of color values
    """
    if theme is None:
        theme = get_theme_manager().get_actual_theme()

    if theme == "dark":
        return DARK_COLORS.copy()
    return LIGHT_COLORS.copy()


def load_base_stylesheet() -> str:
    """
    Load the base stylesheet template from resources.

    Returns:
        The stylesheet template content as a string.
    """
    qss_path = get_resources_path() / "styles" / "base.qss"

    if qss_path.exists():
        return qss_path.read_text()

    return ""


def generate_stylesheet(theme: str = None) -> str:
    """
    Generate a complete stylesheet for the specified or current theme.

    Args:
        theme: 'light' or 'dark'. If None, uses current theme.

    Returns:
        The complete stylesheet with colors substituted.
    """
    template = load_base_stylesheet()
    if not template:
        return ""

    colors = get_colors(theme)

    # Substitute all color placeholders
    stylesheet = template
    for key, value in colors.items():
        stylesheet = stylesheet.replace(f"{{{key}}}", value)

    return stylesheet


def load_stylesheet() -> str:
    """
    Load the stylesheet for the current theme.

    This is the main function used by the application to get the
    appropriate stylesheet based on the current theme setting.

    Returns:
        The complete stylesheet with colors substituted.
    """
    return generate_stylesheet()


def get_icon(name: str, color: Optional[str] = None) -> QIcon:
    """
    Load an SVG icon from resources, optionally tinting it.

    Args:
        name: Icon name (without .svg extension)
        color: Optional hex color to tint the icon

    Returns:
        QIcon loaded from resources
    """
    icon_path = get_resources_path() / "icons" / f"{name}.svg"

    if not icon_path.exists():
        return QIcon()

    if color is None:
        return QIcon(str(icon_path))

    # Load and tint the SVG
    renderer = QSvgRenderer(str(icon_path))
    pixmap = QPixmap(QSize(64, 64))
    pixmap.fill(Qt.transparent)

    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()

    return QIcon(pixmap)


def apply_theme(app: QApplication) -> None:
    """
    Apply the FlowKit theme to the application.

    This applies the stylesheet and sets the application font.
    It also sets up the ThemeManager with saved preferences.

    Args:
        app: The QApplication instance
    """
    # Set application font (uses system fonts)
    app_font = get_app_font(12)
    app.setFont(app_font)

    # Initialize theme manager with saved settings
    settings = get_settings()
    theme_manager = get_theme_manager()

    # Load saved theme preference
    saved_mode = settings.get_theme_mode()
    theme_manager.set_mode(saved_mode)

    # Connect theme changes to stylesheet updates
    def on_theme_changed(theme: str):
        stylesheet = generate_stylesheet(theme)
        if stylesheet:
            app.setStyleSheet(stylesheet)

    theme_manager.theme_changed.connect(on_theme_changed)

    # Apply initial stylesheet
    stylesheet = generate_stylesheet()
    if stylesheet:
        app.setStyleSheet(stylesheet)


def set_theme_mode(mode: ThemeMode, app: QApplication = None) -> None:
    """
    Set the theme mode and update the application.

    Args:
        mode: The ThemeMode to set
        app: Optional QApplication instance. If None, uses QApplication.instance()
    """
    if app is None:
        app = QApplication.instance()

    # Update theme manager
    theme_manager = get_theme_manager()
    theme_manager.set_mode(mode)

    # Save preference
    settings = get_settings()
    settings.set_theme_mode(mode)

    # Apply new stylesheet
    if app:
        stylesheet = generate_stylesheet()
        if stylesheet:
            app.setStyleSheet(stylesheet)


def cycle_theme(app: QApplication = None) -> ThemeMode:
    """
    Cycle through theme modes and update the application.

    Args:
        app: Optional QApplication instance

    Returns:
        The new ThemeMode
    """
    if app is None:
        app = QApplication.instance()

    theme_manager = get_theme_manager()
    new_mode = theme_manager.cycle_mode()

    # Save preference
    settings = get_settings()
    settings.set_theme_mode(new_mode)

    # Apply new stylesheet
    if app:
        stylesheet = generate_stylesheet()
        if stylesheet:
            app.setStyleSheet(stylesheet)

    return new_mode


def get_current_theme() -> str:
    """
    Get the current actual theme.

    Returns:
        'light' or 'dark'
    """
    return get_theme_manager().get_actual_theme()


def get_current_mode() -> ThemeMode:
    """
    Get the current theme mode setting.

    Returns:
        ThemeMode enum value
    """
    return get_theme_manager().mode


def is_dark_mode() -> bool:
    """
    Check if the current actual theme is dark mode.

    This helper provides a simple boolean check for dark mode,
    useful for widgets that need to adjust their appearance
    based on the current theme.

    Returns:
        True if dark mode is active, False if light mode
    """
    return get_theme_manager().is_dark()
