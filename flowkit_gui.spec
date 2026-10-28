# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec file for Flow Harvest (FlowKit GUI) macOS .app bundle."""

import os
import site
import sys
from pathlib import Path

block_cipher = None
ROOT = Path(SPECPATH)

a = Analysis(
    [str(ROOT / 'run_flow_harvest.py')],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        (str(ROOT / 'flowkit_gui' / 'resources'), 'flowkit_gui/resources'),
        # FlowKit's XSD schema files — required at import time
        (os.path.join(site.getsitepackages()[0], 'flowkit', '_resources'), 'flowkit/_resources'),
    ],
    hiddenimports=[
        # Qt modules
        'PyQt5.QtSvg',
        'PyQt5.QtWidgets',
        'PyQt5.QtGui',
        'PyQt5.QtCore',
        # FlowKit and scientific stack
        'flowkit',
        'numpy',
        'pandas',
        'scipy',
        'scipy.optimize',
        'scipy.stats',
        'numexpr',
        'bottleneck',
        'openpyxl',
        'darkdetect',
        'natsort',
        'psutil',
        # macOS integration
        'AppKit',
        'Foundation',
        'objc',
        # FlowKit GUI modules
        'flowkit_gui',
        'flowkit_gui.models',
        'flowkit_gui.models.workspace_model',
        'flowkit_gui.models.gate_tree_model',
        'flowkit_gui.models.keywords_model',
        'flowkit_gui.models.statistics_model',
        'flowkit_gui.models.sample_selection_model',
        'flowkit_gui.models.gate_marker_matrix_model',
        'flowkit_gui.models.wsp_metadata_parser',
        'flowkit_gui.views',
        'flowkit_gui.views.main_window',
        'flowkit_gui.views.splash_screen',
        'flowkit_gui.views.export_summary_dialog',
        'flowkit_gui.views.gate_marker_matrix_view',
        'flowkit_gui.views.styled_tree_delegate',
        'flowkit_gui.views.colored_gate_tree_delegate',
        'flowkit_gui.exporters',
        'flowkit_gui.exporters.xlsx_exporter',
        'flowkit_gui.exporters.export_config',
        'flowkit_gui.utils',
        'flowkit_gui.utils.theme',
        'flowkit_gui.utils.theme_manager',
        'flowkit_gui.utils.settings_manager',
        'flowkit_gui.utils.colors_light',
        'flowkit_gui.utils.colors_dark',
        'flowkit_gui.utils.logging_config',
        'flowkit_gui.utils.mfi_calculations',
        'flowkit_gui.utils.animations',
        'flowkit_gui.utils.cache',
        'flowkit_gui.utils.cancellation',
        'flowkit_gui.utils.fcs_discovery',
        'flowkit_gui.utils.memory_utils',
        'flowkit_gui.utils.timing',
        'flowkit_gui.utils.wait_cursor',
        'flowkit_gui.config',
        'flowkit_gui.config.defaults',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib',
        'tkinter',
        'IPython',
        'jupyter',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='FlowHarvest',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=True,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='FlowHarvest',
)

app = BUNDLE(
    coll,
    name='Flow Harvest.app',
    icon=None,
    bundle_identifier='io.github.jwreda.flowharvest',
    info_plist={
        'CFBundleDisplayName': 'Flow Harvest',
        'CFBundleShortVersionString': '0.1.0',
        'CFBundleVersion': '0.1.0',
        'NSHighResolutionCapable': True,
        'LSMinimumSystemVersion': '10.15',
        'CFBundleDocumentTypes': [
            {
                'CFBundleTypeName': 'FlowJo Workspace',
                'CFBundleTypeExtensions': ['wsp'],
                'CFBundleTypeRole': 'Viewer',
            },
        ],
    },
)
