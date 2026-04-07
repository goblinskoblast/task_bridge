@echo off
echo Starting TaskBridge...
echo.

REM Проверка виртуального окружения
if not exist "venv\Scripts\activate.bat" (
    echo ERROR: Virtual environment not found!
    echo Please run: python -m venv venv
    pause
    exit /b 1
)

REM Проверка React сборки
if not exist "webapp\dist\index.html" (
    echo WARNING: React app not built!
    echo Building React application...
    cd webapp
    call npm install
    call npm run build
    cd ..
    echo React app built successfully!
    echo.
)

REM Активация виртуального окружения
call venv\Scripts\activate.bat

echo [1/3] Starting Telegram Bot...
start "TaskBridge Bot" cmd /k "cd /d %~dp0 && venv\Scripts\activate.bat && python main.py"

timeout /t 3 /nobreak >nul

echo [2/3] Starting FastAPI WebApp...
start "TaskBridge WebApp" cmd /k "cd /d %~dp0 && venv\Scripts\activate.bat && uvicorn webapp.app:app --host 0.0.0.0 --port 8000 --reload"

timeout /t 2 /nobreak >nul

echo [3/3] All services started!
echo.
echo Bot: Running in separate window
echo WebApp: http://localhost:8000
echo.
echo Press any key to open WebApp in browser...
pause >nul

start http://localhost:8000

echo.
echo TaskBridge is running!
echo Close this window or press Ctrl+C to continue...
pause
