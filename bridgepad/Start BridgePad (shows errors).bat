@echo off
cd /d "%~dp0"
echo BridgePad is running. Close this window or the BridgePad window to quit.
py -3 -m padmap
if errorlevel 1 python -m padmap
pause
