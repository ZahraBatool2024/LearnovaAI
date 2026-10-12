@echo off
cd /d "%~dp0"
echo.
echo ========================================
echo       StudyHub AI - FastAPI Backend
echo ========================================
echo.
if exist .venv\Scripts\activate.bat call .venv\Scripts\activate.bat
echo Backend URL: http://127.0.0.1:8000
echo API docs:    http://127.0.0.1:8000/docs
echo.
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
pause
