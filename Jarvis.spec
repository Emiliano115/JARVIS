import os

spec_path = globals().get("SPEC") or os.path.join(os.getcwd(), "Jarvis.spec")
project = os.path.dirname(os.path.abspath(spec_path))


datas = [
    (project + r"\V5.html", "."),
    (project + r"\jarvis_logo.svg", "."),
]
model_path = os.path.join(project, "models", "hand_landmarker.task")
if os.path.exists(model_path):
    datas.append((model_path, "models"))
binaries = []
hiddenimports = [
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtSvg",
    "mediapipe",
    "sounddevice",
    "edge_tts",
    "googleapiclient.discovery",
    "google.oauth2.credentials",
]

hiddenimports += [
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "PySide6.QtNetwork",
    "PySide6.QtWebChannel",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "mediapipe.tasks.python",
    "mediapipe.tasks.python.vision",
    "edge_tts.communicate",
]

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
