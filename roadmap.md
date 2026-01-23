# FlowKit GUI Roadmap

This file tracks planned enhancements and future feature ideas.

## Urgent: Compensation & Unmixing

See [docs/unmixing-vs-compensation.md](docs/unmixing-vs-compensation.md) for full explanation of these concepts.

### Completed
- [x] Document unmixing vs compensation distinction (2026-01-22)
- [x] Parse per-sample compensation assignments from WSP with colors (2026-01-22)
- [x] New WSP-based compensation scanning (distinguishes 'none' from 'missing') (2026-01-22)
- [x] Show compensation matrix colors in sample list (colored dots) (2026-01-22)
- [x] Update compensation info banner (blue informational vs yellow warning) (2026-01-22)

### Completed (Compensation Phase 1)
- [x] Add collapsible compensation details panel with matrix legend (2026-01-22)

### Planned (Compensation Phase 2)

### Planned
- [ ] Handle edge cases (multiple matrices, missing assignments)
- [ ] Export compensation matrix values to Excel
- [ ] Allow user to override per-sample compensation assignments

## Planned Enhancements

### Session Configuration
- [ ] Design portable config format (JSON) for session settings
- [ ] Export button to save current selections to config file
- [ ] Import button to load saved config files
- [ ] Compatibility validation (workspace fingerprint matching)
- [ ] Fuzzy matching for samples with changed paths/volume names
- [ ] Graceful handling of new/removed gates and compensation matrices
- [ ] User feedback on partial matches (what matched, what didn't)

### Matrix Interaction
- [ ] Expandable tips/help overlay for matrix controls (hover "?" icon for full instructions)
- [ ] Keyboard navigation in matrix (arrow keys to move, space to toggle)
- [ ] Undo/redo for matrix selections

### Export Features
- [ ] CSV export option alongside Excel
- [ ] Custom export templates

### UI/UX
- [ ] Dark mode theme option
- [ ] Customizable color palettes for matrix checkboxes
- [ ] Remember window size/position between sessions

## Completed

- [x] Drag to toggle checkboxes in matrix (2026-01-22)
- [x] Shift+drag rectangle selection with context menu (2026-01-22)
