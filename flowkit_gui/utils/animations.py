"""
Animation utilities for FlowKit GUI.

Provides animated widgets for visual effects:
- AnimatedButton: Shadow animation on hover
- HoverMixin: Smooth background color transitions
- FadeTransition: Panel/tab switching effects
"""

from PyQt5.QtWidgets import QPushButton, QGraphicsDropShadowEffect
from PyQt5.QtCore import QPropertyAnimation, QEasingCurve, pyqtProperty
from PyQt5.QtGui import QColor

# Deep Rose color RGB components (used for shadow effects)
SHADOW_COLOR_RGB = (233, 30, 140)


class AnimatedButton(QPushButton):
    """
    QPushButton with animated drop shadow on hover.

    Features:
    - Drop shadow that fades in on hover (0 -> 0.3 opacity)
    - 200ms transition with OutCubic easing
    - Primary vs secondary styling support

    Example:
        button = AnimatedButton("Click Me", primary=True)
        button.clicked.connect(on_click)
    """

    def __init__(self, text="", parent=None, primary=True):
        """
        Initialize AnimatedButton.

        Args:
            text: Button label text
            parent: Parent widget
            primary: If True, uses stronger shadow effect (0.3 opacity);
                     if False, uses subtle shadow (0.15 opacity)
        """
        super().__init__(text, parent)

        self._primary = primary
        self._shadow_opacity = 0.0

        # Set up drop shadow effect using Deep Rose color
        self._shadow = QGraphicsDropShadowEffect(self)
        self._shadow.setBlurRadius(8)
        self._shadow.setOffset(0, 2)
        self._shadow.setColor(QColor(*SHADOW_COLOR_RGB, 0))  # Start transparent
        self.setGraphicsEffect(self._shadow)

        # Animation for shadow opacity
        self._shadow_anim = QPropertyAnimation(self, b"shadowOpacity")
        self._shadow_anim.setDuration(200)
        self._shadow_anim.setEasingCurve(QEasingCurve.OutCubic)

    def enterEvent(self, event):
        """Animate shadow in on hover."""
        self._shadow_anim.stop()
        self._shadow_anim.setStartValue(self._shadow_opacity)
        self._shadow_anim.setEndValue(0.3 if self._primary else 0.15)
        self._shadow_anim.start()
        super().enterEvent(event)

    def leaveEvent(self, event):
        """Animate shadow out on leave."""
        self._shadow_anim.stop()
        self._shadow_anim.setStartValue(self._shadow_opacity)
        self._shadow_anim.setEndValue(0.0)
        self._shadow_anim.start()
        super().leaveEvent(event)

    @pyqtProperty(float)
    def shadowOpacity(self):
        """Get current shadow opacity (0.0 to 1.0)."""
        return self._shadow_opacity

    @shadowOpacity.setter
    def shadowOpacity(self, value):
        """
        Set shadow opacity and update the shadow color.

        Args:
            value: Opacity from 0.0 (transparent) to 1.0 (opaque)
        """
        self._shadow_opacity = value
        alpha = int(value * 255)
        self._shadow.setColor(QColor(*SHADOW_COLOR_RGB, alpha))

    def set_primary(self, primary):
        """
        Change the button's primary/secondary styling.

        Args:
            primary: If True, uses stronger shadow effect
        """
        self._primary = primary


class HoverMixin:
    """
    Mixin class for widgets needing smooth hover background transitions.

    This mixin provides smooth color transitions when hovering over widgets.
    The widget's background color animates from start_color to end_color
    on hover, and back to start_color when the mouse leaves.

    Usage:
        class MyWidget(QWidget, HoverMixin):
            def __init__(self):
                super().__init__()
                self.setup_hover_animation(
                    start_color=QColor("#FFFFFF"),
                    end_color=QColor("#FFF0F5"),
                    duration=150
                )

            def enterEvent(self, event):
                self._hover_anim.stop()
                self._hover_anim.setStartValue(self._bg_color)
                self._hover_anim.setEndValue(self._end_color)
                self._hover_anim.start()
                super().enterEvent(event)

            def leaveEvent(self, event):
                self._hover_anim.stop()
                self._hover_anim.setStartValue(self._bg_color)
                self._hover_anim.setEndValue(self._start_color)
                self._hover_anim.start()
                super().leaveEvent(event)

    Note:
        The widget using this mixin must also inherit from a QObject-based
        class (like QWidget) for the pyqtProperty to work correctly.
    """

    def setup_hover_animation(self, start_color, end_color, duration=150):
        """
        Set up hover color animation.

        Args:
            start_color: QColor for normal (non-hover) state
            end_color: QColor for hover state
            duration: Animation duration in milliseconds (default: 150ms)
        """
        self._bg_color = start_color
        self._start_color = start_color
        self._end_color = end_color

        self._hover_anim = QPropertyAnimation(self, b"backgroundColor")
        self._hover_anim.setDuration(duration)
        self._hover_anim.setEasingCurve(QEasingCurve.OutCubic)

    @pyqtProperty(QColor)
    def backgroundColor(self):
        """Get current background color."""
        return getattr(self, '_bg_color', QColor())

    @backgroundColor.setter
    def backgroundColor(self, color):
        """
        Set background color using palette to avoid overwriting stylesheets.

        Args:
            color: QColor to set as background
        """
        self._bg_color = color
        # Use palette instead of setStyleSheet to preserve existing styles
        palette = self.palette()
        palette.setColor(self.backgroundRole(), color)
        self.setPalette(palette)
        self.setAutoFillBackground(True)


class FadeTransition:
    """
    Utility for fade transitions between panels.

    This class provides a framework for implementing fade-in/fade-out
    transitions when switching between panels or tabs in the UI.

    Note:
        This is a placeholder for future implementation.
        Full fade transitions require more complex widget manipulation
        involving QGraphicsOpacityEffect and coordinated animations
        between the outgoing and incoming widgets.

    Example (future implementation):
        transition = FadeTransition(duration=250)
        transition.switch(old_panel, new_panel)
    """

    def __init__(self, duration=250):
        """
        Initialize FadeTransition.

        Args:
            duration: Transition duration in milliseconds (default: 250ms)
        """
        self._duration = duration

    @property
    def duration(self):
        """Get transition duration in milliseconds."""
        return self._duration

    @duration.setter
    def duration(self, value):
        """
        Set transition duration.

        Args:
            value: Duration in milliseconds (must be positive)

        Raises:
            ValueError: If value is not positive
        """
        if value <= 0:
            raise ValueError(f"Duration must be positive, got {value}")
        self._duration = value
