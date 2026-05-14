#!/usr/bin/env bash
# Production entrypoint: starts the API server + Polymarket bot in parallel
set -e

# Start the Polymarket bot in the background
python3 scripts/polymarket_bot/main.py &
BOT_PID=$!

# Start the API server in the foreground (keeps the container alive)
node --enable-source-maps artifacts/api-server/dist/index.mjs &
API_PID=$!

# Forward signals to both processes
trap "kill $BOT_PID $API_PID 2>/dev/null; exit" SIGTERM SIGINT

# Wait for either process to exit
wait -n
