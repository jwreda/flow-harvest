# MFI-Gate Matrix Drag & Rectangle Selection Design

**Date:** 2026-01-22
**Status:** Approved

## Overview

Add drag functionality to the MFI-gate matrix for faster checkbox selection, plus rectangular selection for bulk operations.

## Features

### 1. Drag Toggle Mode

When the user clicks and holds on a matrix cell, drag mode activates. The state of that first cell determines the "paint action":
- If the first cell was **unchecked** → dragging paints **checks**
- If the first cell was **checked** → dragging paints **unchecks**

As the mouse moves while held, any cell the cursor enters gets the paint action applied. Visual feedback shows cells being affected with a subtle highlight overlay.

### 2. Rectangular Selection (Shift+Drag)

When the user holds **Shift** and drags, a selection rectangle is drawn from the start cell to the current cell. The rectangle visually highlights all cells within its bounds.

On mouse release, a **context menu** appears with three options:
- **Check All** - Sets all cells in rectangle to checked
- **Uncheck All** - Sets all cells in rectangle to unchecked
- **Toggle All** - Flips each cell's current state

If the user clicks outside the menu or presses Escape, the selection is cancelled.

### 3. Visual Feedback

- **Drag toggle mode:** Cells get highlighted as the cursor passes over them. Subtle green tint for "will check", subtle pink tint for "will uncheck"
- **Rectangle mode:** The entire rectangle region gets a semi-transparent pink overlay with a dashed border

### 4. Hint Text

A subtle hint label below the matrix:
- Text: `Drag to toggle • Shift+drag for rectangle select`
- Style: Small font (9pt), gray color (#888)

## Implementation

### State Tracking (in GateMarkerMatrixView)

```python
self._is_dragging: bool = False
self._drag_paint_checked: bool = True  # Action to apply during drag
self._dragged_cells: Set[Tuple[int, int]] = set()  # Cells affected this drag
self._is_rect_selecting: bool = False
self._rect_start: Optional[QModelIndex] = None
self._rect_end: Optional[QModelIndex] = None
```

### Model Addition

New method in `GateMarkerMatrixModel`:

```python
def apply_to_region(self, start_row: int, start_col: int,
                    end_row: int, end_col: int, action: str) -> None:
    """Apply action to rectangular region. Action: 'check', 'uncheck', 'toggle'"""
```

### Event Flow

1. `mousePressEvent` - Detect click, check for Shift modifier, initialize drag state
2. `mouseMoveEvent` - Update highlights, apply toggle for drag mode
3. `mouseReleaseEvent` - Finalize drag or show rectangle context menu

### Files Modified

| File | Changes |
|------|---------|
| `flowkit_gui/views/gate_marker_matrix_view.py` | Drag tracking, rectangle selection, highlight rendering, hint label |
| `flowkit_gui/models/gate_marker_matrix_model.py` | Add `apply_to_region()` method |

## Testing

- Manual testing with existing WSP file
- Verify drag toggle across rows/columns
- Verify Shift+drag rectangle with all three menu options
- Verify hint text displays correctly
- Test at different zoom levels
