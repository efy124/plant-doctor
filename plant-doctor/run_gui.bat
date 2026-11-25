@echo off
REM Plant Doctor - double-click to open the graphical interface.
cd /d "%~dp0"
where python >nul 2>nul
if %errorlevel%==0 (python gui.py) else (py -3 gui.py)
if errorlevel 1 pause
