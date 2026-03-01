"""
Animation utilities for FlowKit GUI.

Provides animated widgets for visual effects:
- AnimatedButton: Shadow animation on hover
- SpecularHoverButton: Theme-aware hover with glint effect
"""

from PyQt5.QtWidgets import QPushButton, QGraphicsDropShadowEffect
from PyQt5.QtCore import QPropertyAnimation, QEasingCurve, pyqtProperty, Qt
from PyQt5.QtGui import QColor, QPainter, QPen, QLinearGradient

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


class SpecularHoverButton(QPushButton):
    """
    QPushButton with theme-aware hover effects.

    Dark mode: Animated pink glint that slides across the top edge,
    like light bouncing off brilliant glass.

    Light mode: Sharp drop shadow with subtle lift animation.

    Example:
        button = SpecularHoverButton("Click Me", primary=True)
        button.clicked.connect(on_click)
    """

    # Pink glint color
    GLINT_COLOR = QColor(255, 105, 180, 200)  # Hot pink with alpha
    GLINT_WIDTH = 30  # Width of the glint segment in pixels

    def __init__(self, text="", parent=None, primary=True):
        """
        Initialize SpecularHoverButton.

        Args:
            text: Button label text
            parent: Parent widget
            primary: If True, uses stronger effects
        """
        super().__init__(text, parent)

        self._primary = primary
        self._glint_position = -1.0  # -1 means not visible, 0-1 is position
        self._shadow_opacity = 0.0  # Initialize before creating animations
        self._is_hovered = False

        # Set up drop shadow for light mode
        self._shadow = QGraphicsDropShadowEffect(self)
        self._shadow.setBlurRadius(3)
        self._shadow.setOffset(2, 3)
        self._shadow.setColor(QColor(0, 0, 0, 0))  # Start transparent
        self.setGraphicsEffect(self._shadow)

        # Animation for glint position (dark mode)
        self._glint_anim = QPropertyAnimation(self, b"glintPosition")
        self._glint_anim.setDuration(400)
        self._glint_anim.setEasingCurve(QEasingCurve.InOutCubic)

        # Animation for shadow opacity (light mode)
        self._shadow_anim = QPropertyAnimation(self, b"shadowOpacity")
        self._shadow_anim.setDuration(150)
        self._shadow_anim.setEasingCurve(QEasingCurve.OutCubic)

    def enterEvent(self, event):
        """Start hover animation based on theme."""
        self._is_hovered = True

        # Import here to avoid circular imports
        from .theme import is_dark_mode

        if is_dark_mode():
            # Dark mode: animate glint across top edge
            self._glint_anim.stop()
            self._glint_anim.setStartValue(0.0)
            self._glint_anim.setEndValue(1.0)
            self._glint_anim.start()
        else:
            # Light mode: show sharp shadow
            self._shadow_anim.stop()
            self._shadow_anim.setStartValue(self._shadow_opacity)
            self._shadow_anim.setEndValue(0.4 if self._primary else 0.25)
            self._shadow_anim.start()

        super().enterEvent(event)

    def leaveEvent(self, event):
        """Reset hover animation."""
        self._is_hovered = False

        # Import here to avoid circular imports
        from .theme import is_dark_mode

        if is_dark_mode():
            # Reset glint position
            self._glint_anim.stop()
            self._glint_position = -1.0
            self.update()
        else:
            # Fade out shadow
            self._shadow_anim.stop()
            self._shadow_anim.setStartValue(self._shadow_opacity)
            self._shadow_anim.setEndValue(0.0)
            self._shadow_anim.start()

        super().leaveEvent(event)

    def paintEvent(self, event):
        """Paint the button with optional glint overlay."""
        super().paintEvent(event)

        # Draw glint effect on top edge (dark mode only)
        if self._glint_position >= 0.0 and self._glint_position <= 1.0:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing)

            # Calculate glint position along top edge
            button_width = self.width()
            glint_center = self._glint_position * button_width
            half_width = self.GLINT_WIDTH / 2

            # Create gradient for smooth glint edges
            gradient = QLinearGradient(
                glint_center - half_width, 0,
                glint_center + half_width, 0
            )
            gradient.setColorAt(0.0, QColor(255, 105, 180, 0))
            gradient.setColorAt(0.3, QColor(255, 105, 180, 180))
            gradient.setColorAt(0.5, QColor(255, 255, 255, 220))  # Bright center
            gradient.setColorAt(0.7, QColor(255, 105, 180, 180))
            gradient.setColorAt(1.0, QColor(255, 105, 180, 0))

            # Draw glint line on top edge
            pen = QPen()
            pen.setWidth(2)
            pen.setBrush(gradient)
            painter.setPen(pen)

            # Draw along top edge with slight inset for border radius
            y_pos = 2
            painter.drawLine(
                int(max(4, glint_center - half_width)), y_pos,
                int(min(button_width - 4, glint_center + half_width)), y_pos
            )

            painter.end()

    @pyqtProperty(float)
    def glintPosition(self):
        """Get current glint position (0.0 to 1.0)."""
        return self._glint_position

    @glintPosition.setter
    def glintPosition(self, value):
        """Set glint position and trigger repaint."""
        self._glint_position = value
        self.update()

    @pyqtProperty(float)
    def shadowOpacity(self):
        """Get current shadow opacity."""
        return self._shadow_opacity

    @shadowOpacity.setter
    def shadowOpacity(self, value):
        """Set shadow opacity for light mode effect."""
        self._shadow_opacity = value
        alpha = int(value * 255)
        self._shadow.setColor(QColor(0, 0, 0, alpha))
