# Polymarket Analysis Bot

A Python bot that monitors Polymarket prediction markets, sends Telegram alerts for new markets and price movements, and uses Claude AI for edge analysis.

## Run & Operate

- `pnpm --filter @workspace/api-server run dev` — run the API server (port 5000)
- `python3 scripts/polymarket_bot/main.py` — run the bot directly (requires internet access — use deployed environment)
- `pnpm run typecheck` — full typecheck across all packages
- `pnpm run build` — typecheck + build all packages
- `pnpm --filter @workspace/api-spec run codegen` — regenerate API hooks and Zod schemas from the OpenAPI spec
- `pnpm --filter @workspace/db run push` — push DB schema changes (dev only)
- Required env: `DATABASE_URL` — Postgres connection string

## Stack

- pnpm workspaces, Node.js 24, TypeScript 5.9
- API: Express 5
- DB: PostgreSQL + Drizzle ORM
- Validation: Zod (`zod/v4`), `drizzle-zod`
- API codegen: Orval (from OpenAPI spec)
- Build: esbuild (CJS bundle)
- Bot: Python 3.11, requests, anthropic, schedule, python-telegram-bot

## Where things live

- `scripts/polymarket_bot/main.py` — main bot script with all 5 features
- `scripts/polymarket_bot/run_production.sh` — production entrypoint (runs bot + API server together)
- `lib/api-spec/openapi.yaml` — OpenAPI spec (source of truth for API contracts)
- `lib/db/src/schema/` — Drizzle DB schema

## Architecture decisions

- Bot runs as a VM deployment (always-running) for full internet access and persistent in-memory price history
- Production entrypoint starts both the API server and Python bot as parallel processes
- Price history is stored in a Python dict (in-memory) — sufficient for detecting 1-hour movements
- Claude edge analysis is called per-market at scan time (not cached) to keep analysis fresh
- Telegram messages use HTML parse mode for bold/emoji formatting

## Product

- **Feature 1**: Every 30 min — scans for new markets (< 2 hours old, volume < $5000, politics/economics/geopolitics topic) and sends Telegram alert with Claude's edge analysis
- **Feature 2**: Claude AI (claude-sonnet-4-20250514) analyzes each market's realistic probability and recommends BUY YES / BUY NO / SKIP
- **Feature 3**: Every 2 hours — scans top 20 markets by volume, sends Telegram summary of top 5 by estimated edge
- **Feature 4**: Daily at 7:00 AM GMT+7 — morning report of top 5 markets with YES price and Claude's edge estimate
- **Feature 5**: Every 15 min — detects price movements > 10% in the past hour and sends spike alerts

## User preferences

- Language: Python for the bot
- Config via environment variables: ANTHROPIC_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
- Clear English comments in code
- Graceful error handling with retry logic

## Gotchas

- The bot requires real internet access — it will show DNS errors in the Replit dev environment (sandbox restriction). Deploy as VM for full functionality.
- Morning report fires at 00:00 UTC = 7:00 AM GMT+7
- Price history is in-memory only; it resets on restart (no DB needed for this use case)
- `python-telegram-bot` v22+ uses async by default — the bot uses raw `requests` for Telegram to stay synchronous and avoid event loop conflicts with `schedule`

## Pointers

- See the `pnpm-workspace` skill for workspace structure, TypeScript setup, and package details
