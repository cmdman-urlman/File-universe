# PyInstaller spec for File Universe Explorer - build with build.bat
# One-folder, windowed build: dist\FileUniverseExplorer\FileUniverseExplorer.exe

a = Analysis(
    ["main.py"],
    pathex=["."],
    hiddenimports=[
        "PyQt6.QtTest",              # imported lazily by --selftest
        "OpenGL.platform.win32",
        "OpenGL.arrays.numpymodule",
        "OpenGL.arrays.ctypesarrays",
        "OpenGL.arrays.ctypesparameters",
        "OpenGL.arrays.ctypespointers",
        "OpenGL.arrays.numbers",
        "OpenGL.arrays.strings",
        "OpenGL.arrays.lists",
        "OpenGL.arrays.nones",
    ],
    excludes=["tkinter", "tests", "unittest", "pydoc", "PyQt6.QtWebEngineCore", "PyQt6.QtQuick", "PyQt6.QtQml"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="FileUniverseExplorer",
    console=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="FileUniverseExplorer")
