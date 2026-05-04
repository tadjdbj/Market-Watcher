from datetime import datetime, timedelta, UTC
from pathlib import Path
from zoneinfo import ZoneInfo
import os
import html
import requests
from playwright.sync_api import sync_playwright

OUTPUT_DIR = Path("outputs")
OUTPUT_DIR.mkdir(exist_ok=True)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY", "").strip()

SEND_TELEGRAM = bool(BOT_TOKEN and CHAT_ID)

MARKETS = [
    {
        "symbol": "BTCUSD",
        "name": "Bitcoin",
        "type": "crypto",
        "url": "https://www.tradingview.com/chart/?symbol=BITSTAMP%3ABTCUSD",
        "move_alert_pct": 3.5
    },
    {
        "symbol": "EURUSD",
        "name": "Euro / Dollar",
        "type": "forex",
        "url": "https://www.tradingview.com/chart/?symbol=FX%3AEURUSD",
        "move_alert_pct": 0.6
    },
    {
        "symbol": "XAUUSD",
        "name": "Gold",
        "type": "metal",
        "url": "https://www.tradingview.com/chart/?symbol=OANDA%3AXAUUSD",
        "move_alert_pct": 1.5
    }
]

NEWS_QUERY_MAP = {
    "BTCUSD": ["bitcoin OR btc", "crypto market", "federal reserve"],
    "EURUSD": ["EURUSD OR euro dollar", "eurozone inflation", "US dollar index"],
    "XAUUSD": ["gold price", "federal reserve", "inflation"]
}

POSITIVE_WORDS = {
    "surge", "rally", "gain", "gains", "bullish", "approval", "cut", "cuts",
    "dovish", "breakout", "supportive", "rise", "rises", "beats", "strong"
}

NEGATIVE_WORDS = {
    "drop", "drops", "fall", "falls", "bearish", "hawkish", "war", "tariff",
    "selloff", "crash", "fear", "inflation", "hotter", "misses", "risk", "weak"
}


def safe_float
