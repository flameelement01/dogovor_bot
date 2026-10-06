#!/bin/bash
set -e

# Start Telegram bot in background
python bot.py &
BOT_PID=$!

# Start webhook server in foreground (keeps container alive)
python webhook.py

# If webhook exits, kill bot too
kill $BOT_PID 2>/dev/null || true
