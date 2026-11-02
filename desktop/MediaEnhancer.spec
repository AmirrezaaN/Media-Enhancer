# PyInstaller build for the Windows app. Run from the project root:
#   .venv\Scripts\pyinstaller desktop\MediaEnhancer.spec --noconfirm
import dis
import shutil
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

if sys.version_info[:3] == (3, 10, 0):
    # Python 3.10.0's dis module mishandles EXTENDED_ARG after an argument-less opcode (bpo-45757) and
    # crashes PyInstaller's bytecode scan. This is the fixed function from Python 3.10.1.
    def _unpack_opargs(code):
        extended_arg = 0
        for i in range(0, len(code), 2):
            op = code[i]
            if op >= dis.HAVE_ARGUMENT:
                arg = code[i + 1] | extended_arg
                extended_arg = (arg << 8) if op == dis.EXTENDED_ARG else 0
            else:
                arg = None
                extended_arg = 0
            yield (i, op, arg)

    dis._unpack_opargs = _unpack_opargs

ROOT = Path(SPECPATH).parent
FFMPEG_DIR = Path(shutil.which("ffmpeg")).parent

datas = [
    (str(ROOT / "weights"), "weights"),
    (str(ROOT / "desktop" / "assets"), "assets"),
    (str(FFMPEG_DIR / "ffmpeg.exe"), "ffmpeg"),
    (str(FFMPEG_DIR / "ffprobe.exe"), "ffmpeg"),
]

hiddenimports = (
    collect_submodules("spandrel")
    + collect_submodules("facexlib.detection")
    + collect_submodules("facexlib.parsing")
    + collect_submodules("ccvfi")
)

excludes = [
    "django", "waitress", "whitenoise", "matplotlib", "tkinter", "IPython", "jupyter", "pytest",
    "triton", "torch.utils.tensorboard", "tensorboard",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtQuick", "PySide6.QtQml",
    "PySide6.Qt3DCore", "PySide6.QtMultimedia", "PySide6.QtCharts", "PySide6.QtDataVisualization",
    "PySide6.QtPdf", "PySide6.QtBluetooth", "PySide6.QtSql", "PySide6.QtTest",
]

a = Analysis(
    [str(ROOT / "desktop" / "main.py")],
    pathex=[str(ROOT)],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MediaEnhancer",
    icon=str(ROOT / "desktop" / "assets" / "icon.ico"),
    console=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="MediaEnhancer", upx=False)
