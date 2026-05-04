from datetime import datetime, timedelta, UTC
from pathlib import Path
import os
import requests

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
        "move_alert_pct": 1.8
    },
    {
        "symbol": "EURUSD",
        "name": "Euro / Dollar",
        "type": "forex",
        "move_alert_pct": 0.4
    },
    {
        "symbol": "XAUUSD",
        "name": "Gold",
        "type": "metal",
        "move_alert_pct": 1.0
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
    except:
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
    return {
        "price": price,
        "open": None,
        "high": None,
        "low": None,
        "pct_24h": pct_24h or 0
    }


def get_eurusd_data():
    latest = fetch_json("https://api.frankfurter.app/latest", {"from": "EUR", "to": "USD"})
    prev_date = (datetime.now(UTC).date() - timedelta(days=1)).isoformat()
    prev = fetch_json(f"https://api.frankfurter.app/{prev_date}", {"from": "EUR", "to": "USD"})
    price = safe_float((latest.get("rates") or {}).get("USD"))
    prev_price = safe_float((prev.get("rates") or {}).get("USD"))
    pct_24h = ((price - prev_price) / prev_price * 100) if price and prev_price else 0
    return {
        "price": price,
        "open": prev_price,
        "high": None,
        "low": None,
        "pct_24h": pct_24h
    }


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
        return {
            "price": price,
            "open": None,
            "high": None,
            "low": None,
            "pct_24h": 0
        }
    except:
        return {
            "price": None,
            "open": None,
            "high": None,
            "low": None,
            "pct_24h": 0
        }


def get_market_data(symbol):
    if symbol == "BTCUSD":
        return get_btc_data()
    if symbol == "EURUSD":
        return get_eurusd_data()
    if symbol == "XAUUSD":
        return get_xauusd_data()
    return {"price": None, "open": None, "high": None, "low": None, "pct_24h": 0}


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
    if raw == 1 or raw == 2:
        return 1, "légèrement positif", "Actualité légèrement favorable 🙂"
    if raw <= -3:
        return -2, "négatif", "Flux news sous pression 📉"
    if raw == -1 or raw == -2:
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


def build_message(result):
    symbol = result["symbol"]
    emoji = result["emoji"]
    signal = result["signal"]
    conf = result["confidence"]
    news_bias = result["news_bias"]
    price = result["market"]["price"]
    pct = result["market"]["pct_24h"]
    lev = result["suggested_leverage"]
    amt = result["suggested_risk_eur"]
    reasons = "\n".join([f"• {x}" for x in result["reasons"][:4]])

    head_news = ""
    if result["articles"]:
        head_news = "\n".join(
            [f"• {a['title']} ({a['source']})" for a in result["articles"][:3]]
        )

    msg = f"""{emoji} {symbol} — Signal: {signal}
Prix: {price if price is not None else 'n/a'}
Variation 24h: {pct:.2f}% if isinstance(pct, (int, float)) else pct

Confiance: {conf}%
Biais news: {news_bias}
Levier conseillé: {lev}
Montant risqué conseillé: {amt} €

Pourquoi:
{reasons if reasons else '• Pas assez de données'}

News:
{head_news if head_news else '• Aucune news disponible'}
"""
    return msg.strip()


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
        "suggested_leverage": lev
    }


def main():
    print("Lancement analyse complète...")
    results = [analyze_one(m) for m in MARKETS]
    for r in results:
        text = build_message(r)
        send_telegram(text)
        print(f"[OK] {r['symbol']} envoyé")
    print("Terminé.")


if __name__ == "__main__":
    main()
