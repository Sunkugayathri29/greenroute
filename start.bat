@echo off
chcp 65001 >nul
echo ===================================
echo  GreenRoute - Starting Server
echo ===================================

echo.

REM Activate virtual environment if available
if exist .venv\Scripts\activate.bat (
    call .venv\Scripts\activate.bat
)

REM Install dependencies using python module to avoid PATH issues
python -m pip install -r requirements.txt --quiet

echo.
echo  Server: http://127.0.0.1:8000
echo  Opening in your default browser...
echo.
echo  Press Ctrl+C to stop
echo.

REM Open browser after brief delay in background
start "" http://127.0.0.1:8000

python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
