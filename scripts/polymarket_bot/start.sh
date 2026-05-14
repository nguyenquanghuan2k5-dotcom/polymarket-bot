#!/usr/bin/env bash
# Start the Polymarket Analysis Bot
set -e
cd "$(dirname "$0")/../.."
exec python3 scripts/polymarket_bot/main.py
