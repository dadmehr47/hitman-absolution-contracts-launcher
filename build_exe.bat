@echo off
cd /d "%~dp0"
pip install pyinstaller
pyinstaller --onefile --windowed --name HitmanContracts --add-data "metadata.json;." --add-data "background.png;." launcher.py
echo.
echo Done. Your program is dist\HitmanContracts.exe
pause
