#!/bin/bash

# FlowKit GUI - Dependency Fixer
# Fixes NumPy 2.x compatibility issues with pandas, numexpr, bottleneck
#
# Run this script if you see errors like:
#   "A module that was compiled using NumPy 1.x cannot be run in NumPy 2.x"
#   "AttributeError: _ARRAY_API not found"

echo "FlowKit GUI - Dependency Fixer"
echo "=============================="
echo ""

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Check if we should use project venv
if [ -f "$SCRIPT_DIR/venv/bin/activate" ]; then
    echo "[INFO] Found project virtual environment"
    source "$SCRIPT_DIR/venv/bin/activate"
    echo "[INFO] Activated: $SCRIPT_DIR/venv"
else
    echo "[WARNING] No project venv found at $SCRIPT_DIR/venv"
    echo "[INFO] Using current Python environment: $(which python)"
fi

echo ""
echo "Current package versions:"
python -c "import numpy; print(f'  NumPy: {numpy.__version__}')" 2>/dev/null || echo "  NumPy: not installed"
python -c "import pandas; print(f'  Pandas: {pandas.__version__}')" 2>/dev/null || echo "  Pandas: not installed"
python -c "import numexpr; print(f'  Numexpr: {numexpr.__version__}')" 2>/dev/null || echo "  Numexpr: not installed"
python -c "import bottleneck; print(f'  Bottleneck: {bottleneck.__version__}')" 2>/dev/null || echo "  Bottleneck: not installed"

echo ""
echo "Upgrading packages for NumPy 2.x compatibility..."
echo ""

# Upgrade packages that need to be recompiled for NumPy 2.x
# These minimum versions are known to support NumPy 2.x
pip install --upgrade "pandas>=2.2.0" "numexpr>=2.10.0" "bottleneck>=1.4.0" "numpy>=2.0.0"

echo ""
echo "Verifying installation..."
echo ""

# Test imports
python -c "
import sys
errors = []

try:
    import numpy as np
    print(f'  NumPy {np.__version__}: OK')
except Exception as e:
    errors.append(f'NumPy: {e}')
    print(f'  NumPy: FAILED - {e}')

try:
    import pandas as pd
    print(f'  Pandas {pd.__version__}: OK')
except Exception as e:
    errors.append(f'Pandas: {e}')
    print(f'  Pandas: FAILED - {e}')

try:
    import numexpr
    print(f'  Numexpr {numexpr.__version__}: OK')
except Exception as e:
    errors.append(f'Numexpr: {e}')
    print(f'  Numexpr: FAILED - {e}')

try:
    import bottleneck
    print(f'  Bottleneck {bottleneck.__version__}: OK')
except Exception as e:
    errors.append(f'Bottleneck: {e}')
    print(f'  Bottleneck: FAILED - {e}')

try:
    import flowkit
    print(f'  FlowKit {flowkit.__version__}: OK')
except Exception as e:
    errors.append(f'FlowKit: {e}')
    print(f'  FlowKit: FAILED - {e}')

if errors:
    print()
    print('Some packages failed to import. You may need to:')
    print('  1. Create a fresh virtual environment')
    print('  2. Run: python -m venv venv && source venv/bin/activate')
    print('  3. Run: pip install -e .')
    sys.exit(1)
else:
    print()
    print('All packages loaded successfully!')
    print('You can now run: bash run_flowkit.sh')
"

exit_code=$?
echo ""
if [ $exit_code -eq 0 ]; then
    echo "Fix completed successfully!"
else
    echo "Some issues remain. See messages above."
fi
