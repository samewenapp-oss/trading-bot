"""Minimal Alpaca REST client (paper by default). Docs: https://docs.alpaca.markets/reference"""
import time

import pandas as pd
import requests

PAPER_URL = "https://paper-api.alpaca.markets"
DATA_URL = "https://data.alpaca.markets"


class BrokerError(Exception):
    pass


class AlpacaClient:
    def __init__(self, key: str, secret: str, base_url: str = PAPER_URL, data_url: str = DATA_URL,
                 timeout: float = 15.0):
        self.base_url = base_url.rstrip("/")
        self.data_url = data_url.rstrip("/")
        self.timeout = timeout
        self.s = requests.Session()
        self.s.headers.update({"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret})

    @property
    def is_paper(self) -> bool:
        return "paper" in self.base_url

    def _req(self, method, url, retries=3, **kw):
        """Retries network errors and 5xx/429 on reads. Order submission goes through
        submit_order, which never blindly retries (see below)."""
        last = None
        for attempt in range(retries):
            try:
                r = self.s.request(method, url, timeout=self.timeout, **kw)
                if r.status_code in (429, 500, 502, 503, 504):
                    last = BrokerError(f"{method} {url} -> {r.status_code} {r.text[:200]}")
                elif r.status_code >= 400:
                    raise BrokerError(f"{method} {url} -> {r.status_code} {r.text[:300]}")
                else:
                    return r.json() if r.content else None
            except requests.RequestException as e:
                last = e
            time.sleep(2 ** attempt)
        raise BrokerError(f"giving up after {retries} tries: {last}")

    # --- account ---
    def clock(self):
        return self._req("GET", f"{self.base_url}/v2/clock")

    def account(self):
        return self._req("GET", f"{self.base_url}/v2/account")

    def positions(self) -> dict:
        return {p["symbol"]: p for p in self._req("GET", f"{self.base_url}/v2/positions")}

    # --- orders ---
    def open_orders(self) -> list:
        return self._req("GET", f"{self.base_url}/v2/orders", params={"status": "open", "limit": 500})

    def get_order(self, order_id):
        return self._req("GET", f"{self.base_url}/v2/orders/{order_id}")

    def get_order_by_client_id(self, client_order_id):
        try:
            return self._req("GET", f"{self.base_url}/v2/orders:by_client_order_id",
                             retries=2, params={"client_order_id": client_order_id})
        except BrokerError:
            return None

    def submit_order(self, **payload):
        """Idempotent submit. client_order_id must be deterministic (e.g. entry-SPY-2026-11-23).
        If the request errors or times out, we look the order up by that id instead of
        resubmitting, so a lost confirmation can't create a duplicate order."""
        cid = payload["client_order_id"]
        try:
            return self._req("POST", f"{self.base_url}/v2/orders", retries=1, json=payload)
        except BrokerError as e:
            existing = self.get_order_by_client_id(cid)
            if existing:
                return existing
            raise BrokerError(f"order {cid} failed and was not found at broker: {e}")

    def replace_order(self, order_id, **payload):
        return self._req("PATCH", f"{self.base_url}/v2/orders/{order_id}", retries=1, json=payload)

    def cancel_order(self, order_id):
        return self._req("DELETE", f"{self.base_url}/v2/orders/{order_id}")

    def wait_for_fill(self, order_id, timeout=60, poll=2):
        end = time.time() + timeout
        o = self.get_order(order_id)
        while o["status"] not in ("filled", "canceled", "expired", "rejected") and time.time() < end:
            time.sleep(poll)
            o = self.get_order(order_id)
        return o

    # --- market data ---
    def daily_bars(self, symbol, start: str, end: str, feed="iex") -> pd.DataFrame:
        """Adjusted daily bars. Free accounts use the IEX feed."""
        url = f"{self.data_url}/v2/stocks/{symbol}/bars"
        params = {"timeframe": "1Day", "start": start, "end": end, "adjustment": "all",
                  "feed": feed, "limit": 10000}
        bars = []
        while True:
            j = self._req("GET", url, params=params)
            bars += j.get("bars") or []
            if not j.get("next_page_token"):
                break
            params["page_token"] = j["next_page_token"]
        if not bars:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        df = pd.DataFrame(bars).rename(columns={"o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"})
        df.index = pd.to_datetime(df["t"]).dt.tz_convert("America/New_York").dt.tz_localize(None).dt.normalize()
        return df[["open", "high", "low", "close", "volume"]].sort_index()
