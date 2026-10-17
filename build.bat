@echo off
rem Builds dist\FileUniverseExplorer\FileUniverseExplorer.exe and a zip of it.
rem Uses its own virtual environment (.venv-build) so your Python install is untouched.
setlocal
cd /d "%~dp0"

if not exist .venv-build\Scripts\python.exe (
    echo Creating build environment...
    py -m venv .venv-build || goto :fail
    .venv-build\Scripts\python -m pip install --upgrade pip || goto :fail
)
.venv-build\Scripts\python -m pip install -r requirements.txt pyinstaller || goto :fail

echo Building...
.venv-build\Scripts\python -m PyInstaller --noconfirm --clean file_universe.spec || goto :fail

echo Zipping...
powershell -NoProfile -Command "Compress-Archive -Force -Path 'dist\FileUniverseExplorer' -DestinationPath 'dist\FileUniverseExplorer-win64.zip'" || goto :fail

echo.
echo Done: dist\FileUniverseExplorer\FileUniverseExplorer.exe
echo       dist\FileUniverseExplorer-win64.zip
exit /b 0

:fail
echo Build failed.
exit /b 1
