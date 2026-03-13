@echo off
REM Quick setup script for ngrok tunnel to OpenClaw
REM Run this on your Windows machine to expose OpenClaw to the internet

echo ============================================
echo TaskBridge - OpenClaw ngrok Tunnel Setup
echo ============================================
echo.

REM Check if Docker is running
echo [1/4] Checking if Docker is running...
docker ps >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Docker is not running!
    echo Please start Docker Desktop and try again.
    pause
    exit /b 1
)
echo OK - Docker is running

echo.
echo [2/4] Starting OpenClaw container...
cd C:\openclaws
docker-compose up -d

REM Wait for OpenClaw to start
timeout /t 5 /nobreak >nul

echo.
echo [3/4] Testing OpenClaw connection...
curl -s http://localhost:3000/health >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo WARNING: OpenClaw may not be fully ready yet
    echo Waiting 10 more seconds...
    timeout /t 10 /nobreak >nul
)
echo OK - OpenClaw is responding

echo.
echo [4/4] Starting ngrok tunnel...
echo.
echo ============================================
echo IMPORTANT: Copy the ngrok URL below!
echo It looks like: https://abc123.ngrok.io
echo.
echo You will need this URL for your .env file on the server:
echo OPENCLAW_BASE_URL=https://abc123.ngrok.io
echo ============================================
echo.
echo Press any key to start ngrok...
pause >nul

REM Start ngrok (assumes it's in PATH)
ngrok http 3000

REM If ngrok exits
echo.
echo ngrok tunnel closed.
pause
