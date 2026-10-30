"""Telegram alerts for new signals.

An external scheduler (e.g. cron-job.org every 10-15 minutes) calls
/alerts/check. Each call looks at the most recently closed candle of every
watched market and sends a Telegram message for setups that just appeared.

Configuration (environment variables):
  TELEGRAM_BOT_TOKEN  token from @BotFather
  TELEGRAM_CHAT_ID    chat that receives the alerts
  ALERT_KEY           optional secret required as ?key= on the alert routes
  ALERT_WATCHLIST     market:interval:strategy entries, comma separated
"""

import os
import time

import requests

from .data import fetch_market
from .markets import get_market
from .strategies import STRATEGIES, new_signal

TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"
DEFAULT_WATCHLIST = "gold:4h:combined,nasdaq:4h:combined"

# Signals already announced, so repeated checks within the same candle stay quiet.
_sent = {}
# When the scheduler last called check_alerts, to confirm it is running.
last_check = {"time": None, "count": 0, "results": None}


def watchlist():
    entries = []
    for item in os.environ.get("ALERT_WATCHLIST", DEFAULT_WATCHLIST).split(","):
        market, interval, strategy = item.strip().split(":")
        get_market(market)
        if strategy not in STRATEGIES:
            raise ValueError(f"unknown strategy '{strategy}' in ALERT_WATCHLIST")
        entries.append((market, interval, strategy))
    return entries


def telegram(method, **params):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")
    response = requests.post(TELEGRAM_API.format(token=token, method=method), json=params, timeout=15)
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram: {data.get('description', response.status_code)}")
    return data["result"]


def send_message(text):
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not chat_id:
        raise RuntimeError("TELEGRAM_CHAT_ID is not set")
    return telegram("sendMessage", chat_id=chat_id, text=text, disable_web_page_preview=True)


def recent_chats():
    """Chats that messaged the bot recently, to find TELEGRAM_CHAT_ID."""
    chats = {}
    for update in telegram("getUpdates"):
        chat = (update.get("message") or {}).get("chat")
        if chat:
            chats[chat["id"]] = chat.get("first_name") or chat.get("title") or ""
    return [{"chatId": k, "name": v} for k, v in chats.items()]


def check_alerts(dashboard_url="", send=send_message, fetch=fetch_market):
    results = []
    for market, interval, strategy in watchlist():
        entry = {"market": market, "interval": interval, "strategy": strategy}
        try:
            candles = fetch(market, interval, 400)
            plan = new_signal(candles, strategy, market)
            if not plan:
                entry["status"] = "no_signal"
            else:
                key = (market, interval, strategy, plan["signalTime"], plan["side"])
                if key in _sent:
                    entry["status"] = "already_sent"
                else:
                    send(format_message(market, interval, strategy, plan, candles[-1]["close"], dashboard_url))
                    _sent[key] = time.time()
                    entry["status"] = "sent"
                entry["side"] = plan["side"]
        except Exception as e:
            entry["status"] = "error"
            entry["error"] = str(e)
        results.append(entry)
    last_check.update(time=time.time(), count=last_check["count"] + 1, results=results)
    return results


def format_message(market, interval, strategy, plan, price, dashboard_url=""):
    info = get_market(market)
    long = plan["side"] == "long"
    entry = plan["entry"]

    def dist(level):
        d = level - entry
        size = f"{abs(d):,.2f}" if abs(d) >= 1 else f"{abs(d):.4f}"
        return f"{'+' if d >= 0 else '−'}{size}"

    name = STRATEGIES[strategy]["name"]
    if plan.get("componentName"):
        name += f" ← {plan['componentName']}"
    if plan.get("market"):
        how = "ادخل بسعر السوق الآن"
    else:
        how = f"أمر حد (Limit) في المنطقة {_num(plan['entryZone']['low'])} – {_num(plan['entryZone']['high'])}"
    lines = [
        f"{'🟢 شراء' if long else '🔴 بيع'} — {info['name']} ({info['exness']}) · {interval}",
        f"الاستراتيجية: {name}",
        "",
        f"الدخول: {_num(entry)} — {how}",
        f"الوقف: {_num(plan['stopLoss'])} ({dist(plan['stopLoss'])})",
    ]
    for n, t in enumerate(plan["targets"], 1):
        lines.append(f"الهدف {n}: {_num(t['price'])} ({dist(t['price'])}) · {t['rr']}R")
    lines += [
        "",
        f"السعر وقت الإشارة: {_num(price)}",
        f"⚠️ الأسعار من {info['symbol']}. في Exness استخدم نفس المسافات (بين القوسين) من سعر دخولك.",
        "أغلق 50% عند الهدف 1 وانقل الوقف للدخول. خاطر بـ 1% فقط. ليست نصيحة مالية.",
    ]
    if dashboard_url:
        lines.append(dashboard_url)
    return "\n".join(lines)


def _num(value):
    return f"{value:,.2f}" if abs(value) >= 100 else f"{value:.4f}"
