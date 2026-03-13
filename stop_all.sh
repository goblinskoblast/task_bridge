#!/bin/bash

echo "Stopping TaskBridge services..."
echo ""

# Проверка и остановка бота
if [ -f ".bot.pid" ]; then
    BOT_PID=$(cat .bot.pid)
    if ps -p $BOT_PID > /dev/null 2>&1; then
        echo "Stopping Bot (PID: $BOT_PID)..."
        kill $BOT_PID
        rm .bot.pid
    else
        echo "Bot is not running"
        rm .bot.pid
    fi
else
    echo "Bot PID file not found"
fi

# Проверка и остановка webapp
if [ -f ".webapp.pid" ]; then
    WEBAPP_PID=$(cat .webapp.pid)
    if ps -p $WEBAPP_PID > /dev/null 2>&1; then
        echo "Stopping WebApp (PID: $WEBAPP_PID)..."
        kill $WEBAPP_PID
        rm .webapp.pid
    else
        echo "WebApp is not running"
        rm .webapp.pid
    fi
else
    echo "WebApp PID file not found"
fi

echo ""
echo "All services stopped!"
