"""Tests for icon tinting in theme.py."""

import pytest
from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QIcon, QPixmap, QColor, QImage
from PyQt5.QtCore import QSize


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_get_icon_returns_icon(qapp):
    """get_icon with valid name returns non-null icon."""
    from flowkit_gui.utils.theme import get_icon
    icon = get_icon("folder-sparkle")
    assert not icon.isNull()


def test_get_icon_with_color_returns_icon(qapp):
    """get_icon with color parameter returns non-null icon."""
    from flowkit_gui.utils.theme import get_icon
    icon = get_icon("folder-sparkle", color="#00FF00")
    assert not icon.isNull()


def test_get_icon_tinting_changes_pixels(qapp):
    """Icons tinted with different colors produce different pixmaps."""
    from flowkit_gui.utils.theme import get_icon, clear_icon_cache
    clear_icon_cache()

    icon_red = get_icon("folder-sparkle", color="#FF0000")
    icon_blue = get_icon("folder-sparkle", color="#0000FF")

    pm_red = icon_red.pixmap(QSize(64, 64))
    pm_blue = icon_blue.pixmap(QSize(64, 64))

    img_red = pm_red.toImage()
    img_blue = pm_blue.toImage()

    assert img_red != img_blue


def test_get_icon_nonexistent_returns_null(qapp):
    """get_icon with nonexistent name returns null icon."""
    from flowkit_gui.utils.theme import get_icon
    icon = get_icon("nonexistent-icon-xyz-12345")
    assert icon.isNull()


def test_icon_cache_returns_same_object(qapp):
    """Repeated calls with same args return cached icon."""
    from flowkit_gui.utils.theme import get_icon, clear_icon_cache
    clear_icon_cache()
    icon1 = get_icon("folder-sparkle", color="#FF0000")
    icon2 = get_icon("folder-sparkle", color="#FF0000")
    assert icon1 is icon2


def test_clear_icon_cache(qapp):
    """clear_icon_cache empties the cache."""
    from flowkit_gui.utils.theme import get_icon, clear_icon_cache, _icon_cache
    get_icon("folder-sparkle", color="#FF0000")
    assert len(_icon_cache) > 0
    clear_icon_cache()
    assert len(_icon_cache) == 0
