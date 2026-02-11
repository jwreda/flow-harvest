"""
Dark theme color palette for FlowKit GUI.

This palette defines all colors used in the dark theme,
with a Deep Rose accent color scheme.
"""

COLORS = {
    # Primary accent colors - Deep Rose palette for dark theme
    "primary": "#E91E8C",           # Deep Rose - pops well on dark
    "primary_hover": "#F03DA0",     # Lighter for visibility on dark
    "primary_pressed": "#D81B7A",   # Pressed state
    "primary_light": "#3A1A2A",     # Dark pink tint - selections

    # Background colors
    "background": "#1E1E1E",        # Dark gray - main background
    "surface": "#2D2D2D",           # Slightly lighter - cards, group boxes
    "surface_hover": "#383838",     # Hover on surface

    # Text colors
    "text_primary": "#E0E0E0",      # Light gray - main text
    "text_secondary": "#A0A0A0",    # Medium gray - secondary text
    "text_disabled": "#606060",     # Dark gray - disabled text
    "text_on_primary": "#FFFFFF",   # White - text on primary color

    # Border colors
    "border": "#404040",            # Medium dark gray - standard borders
    "border_hover": "#E91E8C",      # Deep Rose - hover state borders
    "border_focus": "#E91E8C",      # Deep Rose - focused element borders

    # Interactive states
    "selection": "#3A1A2A",         # Dark pink selection
    "alt_row": "#2A1F27",           # Dark rose tint - alternating rows
    "hover": "#2A1A22",             # Darker hover background

    # Status colors (slightly adjusted for dark theme visibility)
    "success": "#3CB371",           # Medium sea green
    "warning": "#FFD54F",           # Lighter amber
    "error": "#FF6B6B",             # Lighter red
    "info": "#4FC3F7",              # Lighter cyan

    # Component-specific
    "scrollbar_handle": "#505050",
    "scrollbar_handle_hover": "#E91E8C",
    "tooltip_bg": "#3D3D3D",
    "tooltip_text": "#E0E0E0",

    # Shadows and overlays
    "shadow": "rgba(0, 0, 0, 0.3)",
    "overlay": "rgba(0, 0, 0, 0.7)",
}
