@echo off
setlocal
cd /d "%~dp0"

rem First run: create venv and install backend dependencies
if not exist "backend\.venv\Scripts\python.exe" (
    echo Creating Python environment...
    python -m venv backend\.venv || goto :fail
    backend\.venv\Scripts\python -m pip install -q -r backend\requirements.txt || goto :fail
)

rem First run or missing build: build the React frontend
if not exist "frontend\dist\index.html" (
    echo Building frontend...
    pushd frontend
    call npm install --no-audit --no-fund || (popd & goto :fail)
    call npm run build || (popd & goto :fail)
    popd
)

echo.
echo Cisco PO Status Tracker running at http://localhost:5000  (Ctrl+C to stop)
start "" http://localhost:5000
backend\.venv\Scripts\python backend\app.py
goto :eof

:fail
echo.
echo Setup failed. See the messages above.
pause
exit /b 1
