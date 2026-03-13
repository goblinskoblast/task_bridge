#!/bin/bash

echo "Starting TaskBridge..."
echo ""

# Проверка виртуального окружения
if [ ! -f "venv/bin/activate" ]; then
    echo "ERROR: Virtual environment not found!"
    echo "Please run: python3 -m venv venv"
    exit 1
fi

# Проверка React сборки
if [ ! -f "webapp/dist/index.html" ]; then
    echo "WARNING: React app not built!"
    echo "Building React application..."
    cd webapp
    npm install
    npm run build
    cd ..
    echo "React app built successfully!"
    echo ""
fi

# Активация виртуального окружения
source venv/bin/activate

echo "[1/3] Starting Telegram Bot..."
nohup python bot/main.py > bot.log 2>&1 &
BOT_PID=$!
echo "Bot started with PID: $BOT_PID"

sleep 3

echo "[2/3] Starting FastAPI WebApp..."
nohup uvicorn webapp.app:app --host 0.0.0.0 --port 8000 --reload > webapp.log 2>&1 &
WEBAPP_PID=$!
echo "WebApp started with PID: $WEBAPP_PID"

sleep 2

echo "[3/3] All services started!"
echo ""
echo "Bot PID: $BOT_PID (logs in bot.log)"
echo "WebApp PID: $WEBAPP_PID (logs in webapp.log)"
echo "WebApp: http://localhost:8000"
echo ""
echo "To stop services, run: kill $BOT_PID $WEBAPP_PID"
echo ""
echo "TaskBridge is running!"

# Сохраняем PIDs в файл для удобного останова
echo "$BOT_PID" > .bot.pid
echo "$WEBAPP_PID" > .webapp.pid

# Опционально открыть браузер (для macOS)
if [[ "$OSTYPE" == "darwin"* ]]; then
    echo "Opening browser..."
    open http://localhost:8000
fi
