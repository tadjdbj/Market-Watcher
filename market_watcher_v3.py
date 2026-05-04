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


def safe_float(x):
    try:
        return float(x)
    except Exception:
        return None


def fetch_json(url, params=None):
    r = requests.get(url, params=params, timeout=20)
    r.raise_for_status()
    return r.json()


def get_btc_data():
    data = fetch_json(
        "https://api.coingecko.com/api/v3/simple/price",
        {"ids": "bitcoin", "vs_currencies": "usd", "include_24hr_change": "true"}
    )
    item = data.get("bitcoin", {})
    price = safe_float(item.get("usd"))
    pct_24h = safe_float(item.get("usd_24h_change"))
    return {"price": price, "pct_24h": pct_24h or 0}


def get_eurusd_data():
    latest = fetch_json("https://api.frankfurter.app/latest", {"from": "EUR", "to": "USD"})
    prev_date = (datetime.now(UTC).date() - timedelta(days=1)).isoformat()
    prev = fetch_json(f"https://api.frankfurter.app/{prev_date}", {"from": "EUR", "to": "USD"})
    price = safe_float((latest.get("rates") or {}).get("USD"))
    prev_price = safe_float((prev.get("rates") or {}).get("USD"))
    pct_24h = ((price - prev_price) / prev_price * 100) if price and prev_price else 0
    return {"price": price, "pct_24h": pct_24h}


def get_xauusd_data():
    try:
        data = fetch_json("https://api.metals.live/v1/spot/gold")
        price = None
        if isinstance(data, list) and data:
            last = data[0]
            if isinstance(last, dict):
                for _, v in last.items():
                    price = safe_float(v)
                    if price is not None:
                        break
        return {"price": price, "pct_24h": 0}
    except Exception:
        return {"price": None, "pct_24h": 0}


def get_market_data(symbol):
    if symbol == "BTCUSD":
        return get_btc_data()
    if symbol == "EURUSD":
        return get_eurusd_data()
    if symbol == "XAUUSD":
        return get_xauusd_data()
    return {"price": None, "pct_24h": 0}


def fetch_news(query):
    if not NEWSAPI_KEY:
        return []
    params = {
        "q": query,
        "language": "en",
        "sortBy": "publishedAt",
        "pageSize": 5,
        "from": (datetime.now(UTC) - timedelta(days=2)).strftime("%Y-%m-%d"),
        "apiKey": NEWSAPI_KEY
    }
    data = fetch_json("https://newsapi.org/v2/everything", params=params)
    return data.get("articles", [])


def collect_news(symbol):
    results = []
    seen = set()
    for q in NEWS_QUERY_MAP.get(symbol, []):
        try:
            for a in fetch_news(q):
                title = (a.get("title") or "").strip()
                desc = (a.get("description") or "").strip()
                url = (a.get("url") or "").strip()
                source = ((a.get("source") or {}).get("name") or "").strip()
                if title and title.lower() not in seen:
                    seen.add(title.lower())
                    results.append({
                        "title": title,
                        "description": desc,
                        "source": source,
                        "url": url
                    })
        except Exception:
            pass
    return results[:8]


def score_news(articles):
    if not articles:
        return 0, "neutre", "Pas assez d'actualité exploitable 📰"

    raw = 0
    for a in articles:
        txt = (a["title"] + " " + a["description"]).lower()
        raw += sum(1 for w in POSITIVE_WORDS if w in txt)
        raw -= sum(1 for w in NEGATIVE_WORDS if w in txt)

    if raw >= 3:
        return 2, "positif", "Flux news plutôt constructif 📈"
    if raw in (1, 2):
        return 1, "légèrement positif", "Actualité légèrement favorable 🙂"
    if raw <= -3:
        return -2, "négatif", "Flux news sous pression 📉"
    if raw in (-1, -2):
        return -1, "légèrement négatif", "Actualité un peu défensive 😐"
    return 0, "neutre", "Actualité mitigée 🤝"


def score_market(symbol, market):
    score = 0
    reasons = []
    pct = market.get("pct_24h") or 0
    price = market.get("price")

    if price is not None:
        reasons.append(f"Prix actuel: {price}")

    if symbol == "BTCUSD":
        if pct >= 2:
            score += 2
            reasons.append("Momentum 24h fort sur BTC 🚀")
        elif pct >= 0.7:
            score += 1
            reasons.append("Momentum 24h haussier sur BTC")
        elif pct <= -2:
            score -= 2
            reasons.append("Momentum 24h baissier marqué sur BTC")
        elif pct <= -0.7:
            score -= 1
            reasons.append("Momentum 24h faible sur BTC")

    elif symbol == "EURUSD":
        if pct >= 0.35:
            score += 2
            reasons.append("Euro en poussée haussière")
        elif pct >= 0.15:
            score += 1
            reasons.append("Euro légèrement ferme")
        elif pct <= -0.35:
            score -= 2
            reasons.append("Dollar reprend clairement la main")
        elif pct <= -0.15:
            score -= 1
            reasons.append("Dollar un peu plus fort")

    elif symbol == "XAUUSD":
        if pct >= 1.0:
            score += 2
            reasons.append("L'or accélère franchement")
        elif pct >= 0.4:
            score += 1
            reasons.append("L'or reste soutenu")
        elif pct <= -1.0:
            score -= 2
            reasons.append("L'or subit une vraie pression")
        elif pct <= -0.4:
            score -= 1
            reasons.append("L'or faiblit légèrement")

    return score, reasons


def final_signal(score):
    if score >= 3:
        return "BUY", "🟢"
    if score <= -3:
        return "SELL", "🔴"
    return "WAIT", "🟡"


def confidence(score):
    return min(92, 52 + abs(score) * 10)


def suggested_risk_eur(signal, conf, capital=1000):
    if signal == "WAIT":
        return 0
    base = capital * 0.01
    boost = (conf - 50) / 100
    return round(base * (1 + boost), 2)


def suggested_leverage(signal, conf, symbol):
    if signal == "WAIT":
        return "x1"
    if symbol == "BTCUSD":
        return "x2 max" if conf < 75 else "x3 max"
    if symbol == "EURUSD":
        return "x3 max" if conf < 75 else "x5 max"
    if symbol == "XAUUSD":
        return "x2 max" if conf < 75 else "x4 max"
    return "x1"


def special_move_alert(symbol, market, total_score):
    pct = abs(market.get("pct_24h") or 0)
    thresholds = {
        "BTCUSD": 3.5,
        "EURUSD": 0.6,
        "XAUUSD": 1.5
    }
    th = thresholds.get(symbol, 2.0)

    if pct >= th or abs(total_score) >= 4:
        direction = "hausse forte" if (market.get("pct_24h") or 0) > 0 else "baisse forte"
        return True, f"⚠️ Alerte spéciale : {direction}"
    return False, "RAS"


def quick_trade_plan(symbol, signal, conf):
    if signal == "WAIT" or conf < 70:
        return {
            "entry_style": "Pas de scalp conseillé",
            "amount_eur": 0,
            "leverage": "x1",
            "hold_time": "0 min"
        }

    if symbol == "BTCUSD":
        amount = 12 if conf < 80 else 18
        lev = "x2 max"
        hold = "20 à 45 min"
    elif symbol == "EURUSD":
        amount = 12 if conf < 80 else 20
        lev = "x3 max"
        hold = "30 à 90 min"
    elif symbol == "XAUUSD":
        amount = 12 if conf < 80 else 18
        lev = "x2 max" if conf < 80 else "x3 max"
        hold = "20 à 60 min"
    else:
        amount = 10
        lev = "x1"
        hold = "30 min max"

    return {
        "entry_style": f"Scalp {signal}",
        "amount_eur": amount,
        "leverage": lev,
        "hold_time": hold
    }


def escape_text(text):
    return html.escape(str(text), quote=False)


def build_message(result):
    symbol = result["symbol"]
    emoji = result["emoji"]
    signal = result["signal"]
    conf = result["confidence"]
    news_bias = result["news_bias"]
    price = result["market"]["price"]
    pct = result["market"]["pct_24h"]
    move_text = result["move_text"]
    quick = result["quick_plan"]

    top_reasons = result["reasons"][:2]
    top_news = result["articles"][:2]

    price_txt = f"{price:.2f}" if isinstance(price, (int, float)) and price is not None else "n/a"
    pct_txt = f"{pct:+.2f}%" if isinstance(pct, (int, float)) else "n/a"
    now = datetime.now(ZoneInfo("Europe/Paris")).strftime("%d/%m %H:%M")

    lines = [
        f"👋 Update {now}",
        f"{emoji} <b>{symbol}</b> | {price_txt} | {pct_txt}",
        f"Signal: <b>{signal}</b> ({conf}%) | News: <b>{escape_text(news_bias)}</b>",
        f"Alerte: <b>{escape_text(move_text)}</b>",
        f"Plan: <b>{escape_text(quick['entry_style'])}</b>",
        f"Mise: <b>{quick['amount_eur']} €</b> | Levier: <b>{escape_text(quick['leverage'])}</b>",
        f"Durée: <b>{escape_text(quick['hold_time'])}</b>"
    ]

    if top_reasons:
        lines.append("Pourquoi:")
        for r in top_reasons:
            lines.append(f"• {escape_text(r)}")

    if top_news:
        lines.append("News:")
        for a in top_news:
            title = escape_text(a.get("title", ""))[:90]
            source = escape_text(a.get("source", ""))[:20]
            lines.append(f"• {title} ({source})")

    msg = "\n".join(lines)
    return msg[:1000]


def send_telegram(text):
    if not SEND_TELEGRAM:
        print(text)
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    r = requests.post(url, data=payload, timeout=20)
    r.raise_for_status()


def send_photo(photo_path, caption):
    if not SEND_TELEGRAM:
        print(caption)
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    with open(photo_path, "rb") as f:
        files = {"photo": f}
        data = {
            "chat_id": CHAT_ID,
            "caption": caption[:1000],
            "parse_mode": "HTML"
        }
        r = requests.post(url, data=data, files=files, timeout=30)
        r.raise_for_status()


def shot_tradingview(symbol, url, out_path):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1600, "height": 900}, device_scale_factor=1)
        page.goto(url, wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(12000)

        try:
            page.mouse.wheel(0, 450)
            page.wait_for_timeout(1500)
        except Exception:
            pass

        try:
            page.screenshot(path=str(out_path), full_page=False)
        except Exception:
            page.screenshot(path=str(out_path), full_page=True)

        browser.close()


def analyze_one(market_cfg):
    symbol = market_cfg["symbol"]
    market = get_market_data(symbol)
    articles = collect_news(symbol)
    news_score, news_bias, news_note = score_news(articles)
    market_score, reasons = score_market(symbol, market)

    total_score = news_score + market_score
    signal, emoji = final_signal(total_score)
    conf = confidence(total_score)
    risk = suggested_risk_eur(signal, conf)
    lev = suggested_leverage(signal, conf, symbol)
    move_alert, move_text = special_move_alert(symbol, market, total_score)
    quick_plan = quick_trade_plan(symbol, signal, conf)

    if news_note:
        reasons.append(news_note)

    return {
        "symbol": symbol,
        "emoji": emoji,
        "signal": signal,
        "confidence": conf,
        "news_bias": news_bias,
        "market": market,
        "reasons": reasons,
        "articles": articles[:3],
        "suggested_risk_eur": risk,
        "suggested_leverage": lev,
        "move_alert": move_alert,
        "move_text": move_text,
        "quick_plan": quick_plan
    }


def build_priority_summary(results):
    alerts = [r for r in results if r.get("move_alert")]
    if not alerts:
        return None

    now = datetime.now(ZoneInfo("Europe/Paris")).strftime("%d/%m %H:%M")
    lines = [f"⚠️ <b>ALERTE PRIORITAIRE</b> {now}"]

    for r in alerts[:3]:
        q = r["quick_plan"]
        pct = r["market"].get("pct_24h") or 0
        pct_txt = f"{pct:+.2f}%"
        lines.append(
            f"• <b>{r['symbol']}</b> | {r['signal']} | {pct_txt} | Mise {q['amount_eur']}€ | {q['leverage']} | {q['hold_time']}"
        )

    return "\n".join(lines)[:1000]


def main():
    print("Lancement analyse complète...")
    results = []

    for m in MARKETS:
        res = analyze_one(m)
        results.append(res)
        image_path = OUTPUT_DIR / f"{res['symbol']}.jpg"

        try:
            shot_tradingview(res["symbol"], m["url"], image_path)
        except Exception as e:
            print(f"[WARN] screenshot failed for {res['symbol']}: {e}")
            image_path = None

        text = build_message(res)

        if image_path and image_path.exists():
            send_photo(str(image_path), text)
        else:
            send_telegram(text)

        print(f"[OK] {res['symbol']} envoyé")

    priority_msg = build_priority_summary(results)
    if priority_msg:
        send_telegram(priority_msg)
        print("[OK] alerte prioritaire envoyée")

    print("Terminé.")


if __name__ == "__main__":
    main()
