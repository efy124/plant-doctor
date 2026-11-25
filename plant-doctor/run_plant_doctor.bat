@echo off
REM Plant Doctor - double-click to start an interactive consultation.
cd /d "%~dp0"
where python >nul 2>nul
if %errorlevel%==0 (python plant_doctor.py %*) else (py -3 plant_doctor.py %*)
pause
