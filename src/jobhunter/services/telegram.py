"""Sending Telegram messages through the family bot (feature 006 FR-001, FR-002).

Only `sendMessage` is used: the bot's own service keeps receiving its updates. The token comes
from TELEGRAM_BOT_TOKEN and is never logged or shown.
"""

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass

import httpx

log = logging.getLogger(__name__)
API = "https://api.telegram.org"
TIMEOUT = 10.0


@dataclass
class Result:
    ok: bool
    message: str


def configured() -> bool:
    return bool(os.environ.get("TELEGRAM_BOT_TOKEN"))


def send(chat_id: str, text: str, transport: httpx.BaseTransport | None = None) -> Result:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        return Result(False, "The Telegram bot isn't configured (TELEGRAM_BOT_TOKEN in .env).")
    if not chat_id:
        return Result(False, "Enter your Telegram chat id first.")
    try:
        with httpx.Client(transport=transport, timeout=TIMEOUT) as client:
            resp = client.post(
                f"{API}/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": text[:4000], "disable_web_page_preview": True},
            )
        data = (
            resp.json()
            if resp.headers.get("content-type", "").startswith("application/json")
            else {}
        )
    except httpx.HTTPError as exc:
        log.warning("telegram send failed: %s", type(exc).__name__)
        return Result(False, "Telegram could not be reached.")
    if resp.status_code == 200 and data.get("ok"):
        return Result(True, "Sent.")
    description = str(data.get("description") or f"error {resp.status_code}")
    if "chat not found" in description.lower():
        return Result(
            False,
            "Telegram says the chat was not found: send /start to the bot first "
            "and check the chat id.",
        )
    if resp.status_code == 401:
        return Result(False, "Telegram rejected the bot token.")
    return Result(False, f"Telegram error: {description[:200]}")


Sender = Callable[[str, str], Result]
