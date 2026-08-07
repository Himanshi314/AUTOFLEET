@echo off
REM AutoFleet AI — start the dashboard.
REM Runs on the Python standard library alone; `pip install anthropic` only if
REM you want live agents instead of the deterministic fallback.
cd /d "%~dp0"
python -X utf8 server.py --port 8600
pause
