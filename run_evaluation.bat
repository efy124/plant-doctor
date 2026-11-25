@echo off
REM Plant Doctor - re-run the evaluation reported in the project report.
REM Charts need matplotlib:  python -m pip install matplotlib
cd /d "%~dp0"
where python >nul 2>nul
if %errorlevel%==0 (set PY=python) else (set PY=py -3)
%PY% evaluate.py --set dev
%PY% evaluate.py --set test
pause
