from PyInstaller.utils.hooks import collect_all

import os

project = os.path.abspath(os.path.dirname(__file__))

datas = [
    (project + r"\V5.html", "."),
    (project + r"\hand_landmarker.task", "."),
]
binaries = []
hiddenimports = [
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtSvg",
    "mediapipe",
    "sounddevice",
    "googleapiclient.discovery",
    "google.oauth2.credentials",
]

for package in ("PySide6", "mediapipe"):
    try:
        package_datas, package_binaries, package_hidden = collect_all(package)
        datas += package_datas
        binaries += package_binaries
        hiddenimports += package_hidden
    except Exception:
        pass

a = Analysis(
    [project + r"\Jarvis_main.py"],
    pathex=[project],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Jarvis",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Jarvis",
)
