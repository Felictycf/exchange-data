import time
from typing import Any

from .http_client import HttpClientError, JsonHttpClient


class LighterClient:
    BASE_URL = "https://mainnet.zklighter.elliot.ai"

    def __init__(self, timeout: float = 10.0):
        self.http = JsonHttpClient(self.BASE_URL, timeout=timeout)

    def get_order_book_details(self) -> list[dict[str, Any]]:
        data = self.http.get("/api/v1/orderBookDetails")
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("orderBookDetails", "order_book_details", "result", "data"):
                value = data.get(key)
                if isinstance(value, list):
                    return value
        raise ValueError("Unexpected orderBookDetails payload")

    def get_order_book_orders(self, market_id: int, limit: int = 250) -> dict[str, Any]:
        try:
            data = self.http.get(
                "/api/v1/orderBookOrders", params={"market_id": market_id, "limit": min(limit, 250)}
            )
        except HttpClientError:
            return {"asks": [], "bids": []}
        if not isinstance(data, dict):
            raise ValueError("Unexpected orderBookOrders payload")
        return data

    def get_recent_trades(self, market_id: int, limit: int = 200) -> list[dict[str, Any]]:
        try:
            data = self.http.get(
                "/api/v1/recentTrades", params={"market_id": market_id, "limit": min(limit, 50)}
            )
        except HttpClientError:
            return []
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("trades", "result", "data"):
                value = data.get(key)
                if isinstance(value, list):
                    return value
        return []

    def get_fundings(
        self,
        market_id: int,
        resolution: str = "1h",
        count_back: int = 200,
    ) -> list[dict[str, Any]]:
        end_ms = int(time.time() * 1000)
        start_ms = end_ms - (30 * 24 * 60 * 60 * 1000)
        try:
            data = self.http.get(
                "/api/v1/fundings",
                params={
                    "market_id": market_id,
                    "resolution": resolution,
                    "start_timestamp": start_ms,
                    "end_timestamp": end_ms,
                    "count_back": count_back,
                },
            )
        except HttpClientError:
            data = {}
        fundings: list[dict[str, Any]] = []
        if isinstance(data, list):
            fundings = data
        elif isinstance(data, dict):
            for key in ("fundings", "result", "data"):
                value = data.get(key)
                if isinstance(value, list):
                    fundings = value
                    break
        if fundings:
            return fundings

        # Fallback to public aggregate funding endpoint when history is empty.
        try:
            fallback = self.http.get("/api/v1/funding-rates")
        except HttpClientError:
            return []
        if isinstance(fallback, dict):
            rates = fallback.get("funding_rates")
            if isinstance(rates, list):
                return [r for r in rates if int(r.get("market_id", -1)) == market_id]
        return []

    def get_candles(
        self,
        market_id: int,
        resolution: str = "1m",
        count_back: int = 300,
        set_timestamp_to_end: bool = True,
    ) -> list[dict[str, Any]]:
        end_ms = int(time.time() * 1000)
        start_ms = end_ms - (7 * 24 * 60 * 60 * 1000)
        try:
            data = self.http.get(
                "/api/v1/candles",
                params={
                    "market_id": market_id,
                    "resolution": resolution,
                    "start_timestamp": start_ms,
                    "end_timestamp": end_ms,
                    "count_back": min(count_back, 500),
                    "set_timestamp_to_end": str(set_timestamp_to_end).lower(),
                },
            )
        except HttpClientError:
            return []
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            compact = data.get("c")
            if isinstance(compact, list):
                return compact
            for key in ("candles", "result", "data"):
                value = data.get(key)
                if isinstance(value, list):
                    return value
        return []
