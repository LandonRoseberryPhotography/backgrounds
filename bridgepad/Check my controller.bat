@echo off
cd /d "%~dp0"
echo Checking what BridgePad can see. Press buttons on your controller.
py -3 -m padmap --diagnose
if errorlevel 1 python -m padmap --diagnose
pause
