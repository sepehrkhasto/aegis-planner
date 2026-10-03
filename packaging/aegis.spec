# SPDX-License-Identifier: GPL-3.0-or-later
# -*- mode: python ; coding: utf-8 -*-
# Build:  pyinstaller packaging/aegis.spec --noconfirm
from pathlib import Path

ROOT = Path(SPECPATH).parent
ICON = str(ROOT / "aegis_desktop" / "assets" / "icon.ico")
VERSION = str(ROOT / "packaging" / "version_info.txt")

a = Analysis(
    [str(ROOT / "run_aegis.py")],
    pathex=[str(ROOT)],
    datas=[(str(ROOT / "aegis_desktop" / "assets"), "assets")],
    hiddenimports=["winsound", "wave"],
    excludes=["tkinter", "PyQt6.QtWebEngineCore", "PyQt6.QtWebEngineWidgets", "PyQt6.QtQml", "PyQt6.QtQuick",
              "PyQt6.QtNetwork", "PyQt6.QtSql", "PyQt6.QtMultimedia", "PyQt6.QtBluetooth", "PyQt6.Qt3DCore",
              "PyQt6.QtDesigner", "PyQt6.QtPdf", "PyQt6.QtTest", "unittest", "pydoc"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="AegisPlanner",
    console=False,          # GUI app: no console window
    icon=ICON,
    version=VERSION,
    upx=False,              # UPX triggers antivirus false positives
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="AegisPlanner")
