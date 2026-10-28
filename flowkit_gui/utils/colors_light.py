"""
Light theme color palette for Flow Harvest.

This palette defines all colors used in the light theme,
with a Deep Rose accent color scheme.
"""

COLORS = {
    # Primary accent colors - Deep Rose palette
    "primary": "#E91E8C",           # Deep Rose - more sophisticated
    "primary_hover": "#D81B7A",     # Hover state
    "primary_pressed": "#C4186E",   # Pressed/active state
    "primary_light": "#FFE8F0",     # Blush - accent light

    # Background colors
    "background": "#FFFFFF",        # Pure white - main background
    "surface": "#F8F9FA",           # Light gray - cards, group boxes
    "surface_hover": "#F0F1F2",     # Slightly darker - hover on surface

    # Text colors
    "text_primary": "#333333",      # Dark gray - main text
    "text_secondary": "#666666",    # Medium gray - secondary text
    "text_disabled": "#999999",     # Light gray - disabled text
    "text_on_primary": "#FFFFFF",   # White - text on primary color

    # Border colors
    "border": "#E0E0E0",            # Soft gray - standard borders
    "border_hover": "#E91E8C",      # Deep Rose - hover state borders
    "border_focus": "#E91E8C",      # Deep Rose - focused element borders

    # Interactive states
    "selection": "#FFDBE8",         # Rose Tint - selected items
    "alt_row": "#FFF5F8",           # Very light pink - alternating rows
    "hover": "#FFF0F5",             # Light Blush - hover background

    # Status colors (keeping these consistent across themes)
    "success": "#28A745",           # Green
    "warning": "#FFC107",           # Amber
    "error": "#DC3545",             # Red
    "info": "#17A2B8",              # Cyan

    # Component-specific
    "scrollbar_handle": "#E0E0E0",
    "scrollbar_handle_hover": "#E91E8C",
    "tooltip_bg": "#333333",
    "tooltip_text": "#FFFFFF",

    # Shadows and overlays
    "shadow": "rgba(0, 0, 0, 0.1)",
    "overlay": "rgba(0, 0, 0, 0.5)",
}
