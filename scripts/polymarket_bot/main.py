"""
Polymarket Analysis Bot
Features:
  1. New Market Alert — every 30 min, alerts on newly created low-volume markets
  2. Edge Analysis via Claude — AI-powered probability estimation per market
  3. Trending Market Scan — every 2 hours, top 5 markets by edge
  4. Morning Report — daily at 7:00 AM GMT+7
  5. Price Movement Alert — alerts when YES price moves >10% in 1 hour
"""

import os
import time
import logging
import requests
import anthropic
import schedule
import asyncio
from datetime import datetime, timezone, timedelta
from telegram import Bot
from telegram.error import TelegramError

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config from environment variables
# ---------------------------------------------------------------------------
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

POLYMARKET_BASE = "https://gamma-api.polymarket.com/markets"
CLAUDE_MODEL = "claude-sonnet-4-20250514"

# In-memory price tracker: market_id -> {price: float, timestamp: datetime}
price_history: dict[str, dict] = {}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def fetch_markets(params: dict, retries: int = 3) -> list[dict]:
    """Fetch markets from Polymarket API with retry logic."""
    for attempt in range(retries):
        try:
            resp = requests.get(POLYMARKET_BASE, params=params, timeout=15)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            log.warning(f"Polymarket API error (attempt {attempt + 1}/{retries}): {e}")
            if attempt < retries - 1:
                time.sleep(5 * (attempt + 1))
    log.error("All retries exhausted for Polymarket API.")
    return []


def send_telegram(message: str) -> None:
    """Send a Telegram message synchronously using requests (no async needed)."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
    }
    for attempt in range(3):
        try:
            resp = requests.post(url, json=payload, timeout=15)
            resp.raise_for_status()
            log.info("Telegram message sent.")
            return
        except requests.RequestException as e:
            log.warning(f"Telegram send error (attempt {attempt + 1}/3): {e}")
            if attempt < 2:
                time.sleep(3)
    log.error("Failed to send Telegram message after 3 attempts.")


def get_claude_analysis(title: str, yes_price_pct: float) -> str:
    """Call Claude to get edge analysis for a market."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    prompt = (
        f"You are a prediction market analyst. "
        f"Market: {title}. "
        f"Current YES price: {yes_price_pct:.1f}%. "
        f"Briefly analyze: "
        f"1) What is the realistic probability? "
        f"2) Edge = your estimate minus market price. "
        f"3) Recommend: BUY YES / BUY NO / SKIP. "
        f"Be concise, max 150 words."
    )
    for attempt in range(3):
        try:
            response = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text.strip()
        except Exception as e:
            log.warning(f"Claude API error (attempt {attempt + 1}/3): {e}")
            if attempt < 2:
                time.sleep(5)
    return "⚠️ Claude analysis unavailable."


def yes_price_pct(market: dict) -> float:
    """Extract YES token price as a percentage (0-100)."""
    try:
        tokens = market.get("tokens", [])
        for token in tokens:
            if token.get("outcome", "").upper() == "YES":
                return float(token.get("price", 0)) * 100
        # Fallback: outcomePrices field
        prices = market.get("outcomePrices", "")
        if prices:
            parts = [p.strip() for p in str(prices).strip("[]").split(",")]
            if parts:
                return float(parts[0]) * 100
    except Exception:
        pass
    return 0.0


def is_politics_economics(market: dict) -> bool:
    """Heuristic check: does this market relate to politics/economics/geopolitics?"""
    keywords = [
        "election", "president", "senate", "congress", "prime minister",
        "government", "gdp", "inflation", "fed", "interest rate", "recession",
        "war", "conflict", "nato", "sanction", "tariff", "trade", "treaty",
        "poll", "vote", "ballot", "economy", "unemployment", "minister",
        "geopolit", "military", "nuclear", "diplomatic", "un ", "g7", "g20",
        "trump", "biden", "modi", "xi ", "putin", "zelensky", "macron",
        "democrat", "republican", "labour", "conservative",
    ]
    text = (market.get("question", "") + " " + market.get("description", "")).lower()
    return any(kw in text for kw in keywords)


def minutes_ago(created_at_str: str) -> int:
    """Return how many minutes ago a market was created."""
    try:
        # Handle both ISO formats
        created_at_str = created_at_str.replace("Z", "+00:00")
        created = datetime.fromisoformat(created_at_str)
        now = datetime.now(timezone.utc)
        delta = now - created
        return int(delta.total_seconds() / 60)
    except Exception:
        return -1


def market_url(market: dict) -> str:
    slug = market.get("slug", "")
    if slug:
        return f"https://polymarket.com/event/{slug}"
    return "https://polymarket.com"


# ---------------------------------------------------------------------------
# Feature 1: New Market Alert (every 30 minutes)
# ---------------------------------------------------------------------------

def check_new_markets() -> None:
    log.info("Checking for new markets...")
    params = {
        "active": "true",
        "limit": 50,
        "order": "createdAt",
        "ascending": "false",
    }
    markets = fetch_markets(params)
    now = datetime.now(timezone.utc)
    two_hours_ago = now - timedelta(hours=2)

    alerted = 0
    for market in markets:
        created_str = market.get("createdAt", "")
        if not created_str:
            continue

        # Only markets created in the last 2 hours
        mins = minutes_ago(created_str)
        if mins < 0 or mins > 120:
            continue

        # Filter: volume < 5000
        volume = float(market.get("volume", 0) or 0)
        if volume >= 5000:
            continue

        # Filter: politics / economics / geopolitics topic
        if not is_politics_economics(market):
            continue

        title = market.get("question", "Unknown Market")
        price = yes_price_pct(market)
        url = market_url(market)

        # Get Claude edge analysis
        analysis = get_claude_analysis(title, price)

        message = (
            f"🆕 <b>NEW MARKET DETECTED</b>\n"
            f"📌 {title}\n"
            f"💰 YES price: {price:.1f}%\n"
            f"📊 Volume: ${volume:,.0f}\n"
            f"⏰ Created: {mins} minutes ago\n"
            f"🔗 {url}\n"
            f"💡 Early entry opportunity — low volume, analyze before crowd moves in\n\n"
            f"🤖 <b>Claude's Analysis:</b>\n{analysis}"
        )
        send_telegram(message)
        alerted += 1

        # Track price for movement alerts
        price_history[market.get("id", title)] = {
            "price": price,
            "timestamp": now,
            "title": title,
        }

    log.info(f"New market check complete. Alerted on {alerted} market(s).")


# ---------------------------------------------------------------------------
# Feature 2: Edge Analysis is embedded in Features 1 and 3 via get_claude_analysis()
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Feature 3: Trending Market Scan (every 2 hours)
# ---------------------------------------------------------------------------

def trending_market_scan() -> None:
    log.info("Running trending market scan...")
    params = {
        "active": "true",
        "limit": 20,
        "order": "volume",
        "ascending": "false",
    }
    markets = fetch_markets(params)
    if not markets:
        log.warning("No markets returned for trending scan.")
        return

    # Collect edge estimates for top markets
    market_edges = []
    for market in markets[:20]:
        title = market.get("question", "Unknown")
        price = yes_price_pct(market)
        volume = float(market.get("volume", 0) or 0)
        analysis = get_claude_analysis(title, price)

        # Parse edge from Claude response (look for numeric edge mention)
        edge_estimate = 0.0
        for line in analysis.split("\n"):
            line_lower = line.lower()
            if "edge" in line_lower:
                # Try to extract a number like "+5%", "-3%", "5 percentage points"
                import re
                numbers = re.findall(r"[+-]?\d+(?:\.\d+)?", line)
                if numbers:
                    try:
                        edge_estimate = abs(float(numbers[0]))
                    except ValueError:
                        pass
                break

        market_edges.append({
            "title": title,
            "price": price,
            "volume": volume,
            "analysis": analysis,
            "edge": edge_estimate,
            "url": market_url(market),
        })

        # Track price
        mid = market.get("id", title)
        now = datetime.now(timezone.utc)
        price_history[mid] = {"price": price, "timestamp": now, "title": title}

    # Sort by edge descending, take top 5
    top5 = sorted(market_edges, key=lambda x: x["edge"], reverse=True)[:5]

    lines = ["📊 <b>TRENDING MARKET SCAN — Top 5 by Edge</b>\n"]
    for i, m in enumerate(top5, 1):
        lines.append(
            f"{i}. <b>{m['title']}</b>\n"
            f"   💰 YES: {m['price']:.1f}% | 📊 Vol: ${m['volume']:,.0f}\n"
            f"   🔗 {m['url']}\n"
            f"   🤖 {m['analysis']}\n"
        )

    send_telegram("\n".join(lines))
    log.info("Trending scan complete.")


# ---------------------------------------------------------------------------
# Feature 4: Morning Report (daily at 7:00 AM GMT+7)
# ---------------------------------------------------------------------------

def morning_report() -> None:
    log.info("Generating morning report...")
    params = {
        "active": "true",
        "limit": 20,
        "order": "volume",
        "ascending": "false",
    }
    markets = fetch_markets(params)
    if not markets:
        log.warning("No markets for morning report.")
        return

    top5 = markets[:5]
    today_str = datetime.now(timezone(timedelta(hours=7))).strftime("%A, %B %d %Y")
    lines = [f"📊 <b>POLYMARKET MORNING REPORT</b>\n📅 {today_str}\n"]

    for i, market in enumerate(top5, 1):
        title = market.get("question", "Unknown")
        price = yes_price_pct(market)
        analysis = get_claude_analysis(title, price)
        url = market_url(market)
        lines.append(
            f"{i}. <b>{title}</b>\n"
            f"   💰 YES: {price:.1f}%\n"
            f"   🔗 {url}\n"
            f"   🤖 {analysis}\n"
        )

    send_telegram("\n".join(lines))
    log.info("Morning report sent.")


# ---------------------------------------------------------------------------
# Feature 5: Price Movement Alert (checked every 15 minutes)
# ---------------------------------------------------------------------------

def check_price_movements() -> None:
    log.info("Checking price movements...")
    params = {
        "active": "true",
        "limit": 50,
        "order": "volume",
        "ascending": "false",
    }
    markets = fetch_markets(params)
    now = datetime.now(timezone.utc)

    for market in markets:
        mid = market.get("id", market.get("question", ""))
        if not mid:
            continue

        title = market.get("question", "Unknown")
        current_price = yes_price_pct(market)

        if mid in price_history:
            prev = price_history[mid]
            prev_price = prev["price"]
            prev_time = prev["timestamp"]

            # Only compare if previous snapshot is within the last 1 hour
            age_minutes = (now - prev_time).total_seconds() / 60
            if age_minutes <= 60:
                change = current_price - prev_price
                if abs(change) >= 10:
                    direction = "📈" if change > 0 else "📉"
                    message = (
                        f"{direction} <b>PRICE SPIKE DETECTED</b>\n"
                        f"📌 {title}\n"
                        f"💰 Moved from {prev_price:.1f}% → {current_price:.1f}% "
                        f"({'+'if change>0 else ''}{change:.1f}%)\n"
                        f"⏱ Over the past {int(age_minutes)} minutes\n"
                        f"🔗 {market_url(market)}\n"
                        f"ℹ️ This may mean: new information entered the market"
                    )
                    send_telegram(message)
                    log.info(f"Price spike alert sent for: {title}")

        # Always update the latest price
        price_history[mid] = {"price": current_price, "timestamp": now, "title": title}

    log.info("Price movement check complete.")


# ---------------------------------------------------------------------------
# Scheduler setup
# ---------------------------------------------------------------------------

def setup_schedule() -> None:
    # Feature 1: New market alert every 30 minutes
    schedule.every(30).minutes.do(check_new_markets)

    # Feature 3: Trending scan every 2 hours
    schedule.every(2).hours.do(trending_market_scan)

    # Feature 4: Morning report at 7:00 AM GMT+7 = 00:00 UTC
    schedule.every().day.at("00:00").do(morning_report)

    # Feature 5: Price movement check every 15 minutes
    schedule.every(15).minutes.do(check_price_movements)

    log.info("All schedules configured.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    log.info("Polymarket Analysis Bot starting up...")

    # Validate required env vars
    missing = [
        k for k in ["ANTHROPIC_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"]
        if not os.environ.get(k)
    ]
    if missing:
        raise SystemExit(f"Missing required environment variables: {', '.join(missing)}")

    # Run all checks immediately on startup so the user gets instant feedback
    log.info("Running initial checks on startup...")
    check_new_markets()
    check_price_movements()

    # Set up recurring schedule
    setup_schedule()

    log.info("Bot is running. Press Ctrl+C to stop.")
    while True:
        schedule.run_pending()
        time.sleep(30)
