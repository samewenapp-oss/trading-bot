import logging
import os

import requests

log = logging.getLogger("bot")


class Notifier:
    """Sends to Telegram if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are set. Never raises."""

    def __init__(self):
        self.token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat = os.getenv("TELEGRAM_CHAT_ID")

    def send(self, text: str):
        log.info("notify: %s", text)
        if not (self.token and self.chat):
            return
        try:
            requests.post(f"https://api.telegram.org/bot{self.token}/sendMessage",
                          json={"chat_id": self.chat, "text": text}, timeout=10)
        except Exception as e:  # a notification failure must never stop trading logic
            log.warning("telegram send failed: %s", e)

    def send_photo(self, path, caption: str = ""):
        if not (self.token and self.chat):
            log.info("chart saved to %s (Telegram not configured)", path)
            return
        try:
            with open(path, "rb") as fh:
                requests.post(f"https://api.telegram.org/bot{self.token}/sendPhoto",
                              data={"chat_id": self.chat, "caption": caption}, files={"photo": fh}, timeout=20)
        except Exception as e:
            log.warning("telegram photo failed: %s", e)
