from __future__ import annotations

import json
import logging
from typing import Any

from exchange_monitor.clients.omni_client import OmniClient

from .utils import now_iso8601, to_float

logger = logging.getLogger(__name__)


def normalize_omni_listing(listing: dict[str, Any], collected_at: str) -> dict[str, Any]:
    ticker = str(listing.get("ticker") or "")
    quotes = listing.get("quotes") or {}
    base_quote = quotes.get("base") or {}
    open_interest = listing.get("open_interest") or {}

    ladder = []
    for tier in ("size_1k", "size_100k", "size_1m"):
        tier_quote = quotes.get(tier)
        if isinstance(tier_quote, dict):
            ladder.append(
                {
                    "tier": tier,
                    "bid": to_float(tier_quote.get("bid")),
                    "ask": to_float(tier_quote.get("ask")),
                    "exchange_ts": quotes.get("updated_at"),
                    "collected_at": collected_at,
                    "raw_json": json.dumps(tier_quote, ensure_ascii=True),
                }
            )

    return {
        "instrument": {
            "exchange": "omni",
            "market_id": ticker,
            "symbol": ticker,
            "base_asset": ticker,
            "quote_asset": "USD",
            "status": "ACTIVE",
            "instrument_type": "rfq_perp",
            "price_decimals": None,
            "size_decimals": None,
            "min_size": None,
            "raw_json": json.dumps(listing, ensure_ascii=True),
        },
        "snapshot": {
            "collected_at": collected_at,
            "exchange_ts": quotes.get("updated_at"),
            "best_bid": to_float(base_quote.get("bid")),
            "best_ask": to_float(base_quote.get("ask")),
            "mark_price": to_float(listing.get("mark_price")),
            "index_price": None,
            "funding_rate": to_float(listing.get("funding_rate")),
            "funding_interval_sec": listing.get("funding_interval_s"),
            "open_interest_long": to_float(open_interest.get("long_open_interest")),
            "open_interest_short": to_float(open_interest.get("short_open_interest")),
            "volume_24h": to_float(listing.get("volume_24h")),
            "raw_json": json.dumps(listing, ensure_ascii=True),
        },
        "fees": {
            "maker_fee": 0.0,
            "taker_fee": 0.0,
            "fee_ccy": "USD",
            "effective_at": collected_at,
            "raw_json": '{"source":"omni_official_doc"}',
        },
        "quote_ladder": ladder,
    }


class OmniCollector:
    def __init__(self, client: OmniClient | None = None):
        self.client = client or OmniClient()

    def collect(self) -> list[dict[str, Any]]:
        logger.info("omni fetch metadata/stats")
        data = self.client.get_stats()
        listings = data.get("listings") or []
        collected_at = now_iso8601()
        normalized = [
            normalize_omni_listing(listing, collected_at)
            for listing in listings
            if isinstance(listing, dict) and listing.get("ticker")
        ]
        logger.info("omni normalized listings=%d", len(normalized))
        return normalized
