@echo off
cd /d "%~dp0"
echo Starting Learnova AI frontend...
python -m http.server 5173
