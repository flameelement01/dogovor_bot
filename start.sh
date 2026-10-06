#!/bin/bash
set -e

# Single process: FastAPI serves the AMO webhook and hosts the Telegram bot in
# webhook mode. Running the bot here instead of as a second process keeps one
# instance per deploy.
exec python webhook.py
