@echo off
echo ===================================
echo  GreenRoute AI — Starting Server
echo ===================================
echo.

REM Install dependencies if needed
pip install -r requirements.txt --quiet

echo.
echo  Server: http://127.0.0.1:8000
echo  Open the link above in your browser
echo.
echo  Press Ctrl+C to stop
echo.

python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
