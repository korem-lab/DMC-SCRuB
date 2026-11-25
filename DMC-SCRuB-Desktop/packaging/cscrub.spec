"""PyInstaller specification for the signed macOS arm64 application."""

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_all,
    collect_data_files,
    collect_submodules,
    copy_metadata,
)

SPEC_DIR = Path(SPECPATH).resolve()
PROJECT = SPEC_DIR.parent
SOURCE = PROJECT / "src"

APP_NAME = "C-SCRuB Desktop"
EXE_NAME = "C-SCRuB-Desktop"
BUNDLE_ID = "edu.columbia.koremlab.cscrub"
VERSION = "0.3.0"
SIGN_IDENTITY = os.environ.get(
    "CSC_IDENTITY",
    "Developer ID Application: Guanlin Chen (2R972T78WJ)",
)

dmc_datas, dmc_binaries, dmc_hiddenimports = collect_all("dmc_scrub")
torchsort_datas, torchsort_binaries, torchsort_hiddenimports = collect_all(
    "torchsort"
)
# pytorch_lightning / lightning_fabric read version.info at import time.
# PyInstaller packs their .py modules but drops these non-Python data files
# unless we collect them explicitly.
lightning_datas = [
    *collect_data_files("pytorch_lightning"),
    *collect_data_files("lightning_fabric"),
    *collect_data_files("lightning_utilities"),
]

datas = [
    (str(SOURCE / "dmcscrub_app" / "resources"), "dmcscrub_app/resources"),
    *copy_metadata("cscrub-desktop"),
    *copy_metadata("DMC-SCRuB"),
    *copy_metadata("pytorch-lightning"),
    *copy_metadata("torchmetrics"),
    *copy_metadata("lightning-utilities"),
    *dmc_datas,
    *torchsort_datas,
    *lightning_datas,
]

binaries = [
    *dmc_binaries,
    *torchsort_binaries,
]

hiddenimports = [
    "dmcscrub_app.backend.process_main",
    *collect_submodules("pandas._libs"),
    *dmc_hiddenimports,
    *torchsort_hiddenimports,
]

excludes = [
    "IPython",
    "jupyter",
    "matplotlib",
    "notebook",
    "pytest",
    "tkinter",
    "torchaudio",
    "torchvision",
    "PySide6.Qt3DCore",
    "PySide6.QtBluetooth",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtDesigner",
    "PySide6.QtMultimedia",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
]

analysis = Analysis(
    [str(SOURCE / "dmcscrub_app" / "main.py")],
    pathex=[str(SOURCE)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name=EXE_NAME,
    debug=False,
    strip=False,
    upx=False,
    console=False,
    target_arch="arm64",
    codesign_identity=SIGN_IDENTITY,
    entitlements_file=None,
    icon=str(SPEC_DIR / "icon.icns"),
)

collect = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name=EXE_NAME,
)

if sys.platform == "darwin":
    app = BUNDLE(
        collect,
        name=f"{APP_NAME}.app",
        icon=str(SPEC_DIR / "icon.icns"),
        bundle_identifier=BUNDLE_ID,
        info_plist={
            "CFBundleName": APP_NAME,
            "CFBundleDisplayName": APP_NAME,
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
            "LSMinimumSystemVersion": "12.0",
            "NSHighResolutionCapable": True,
            "NSRequiresAquaSystemAppearance": False,
        },
    )
