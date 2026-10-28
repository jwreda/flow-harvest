#!/usr/bin/env python3
"""Entry point for Flow Harvest - used by PyInstaller bundle."""
import sys
import os

# Ensure the package is importable
if getattr(sys, 'frozen', False):
    base_path = sys._MEIPASS
else:
    base_path = os.path.dirname(os.path.abspath(__file__))

sys.path.insert(0, base_path)

from flowkit_gui.main import main

main()
