from __future__ import annotations

import json
import logging
from typing import Any

from exchange_monitor.clients.lighter_client import LighterClient

from .utils import ms_to_iso8601, now_iso8601, to_float

logger = logging.getLogger(__name__)


def _extract_best_levels(order_book: dict[str, Any]) -> tuple[float | None, float | None]:
    asks = order_book.get("asks") or []
    bids = order_book.get("bids") or []
    if asks and isinstance(asks[0], dict):
        best_ask = to_float(asks[0].get("price"))
    else:
        best_ask = to_float(asks[0][0]) if asks else None
    if bids and isinstance(bids[0], dict):
        best_bid = to_float(bids[0].get("price"))
    else:
        best_bid = to_float(bids[0][0]) if bids else None
    return best_bid, best_ask


def _extract_funding_rate(payload: dict[str, Any]) -> float | None:
    return to_float(
        payload.get("funding_rate")
        or payload.get("current_funding_rate")
        or payload.get("rate")
        or payload.get("value")
    )


def _latest_funding(fundings: list[dict[str, Any]]) -> dict[str, Any]:
    if not fundings:
        return {}

    def ts(item: dict[str, Any]) -> int:
        raw = item.get("timestamp") or item.get("funding_timestamp")
        try:
            return int(raw)
        except (TypeError, ValueError):
            return -1

    return max(fundings, key=ts)


def normalize_lighter_market_bundle(
    details: dict[str, Any],
    order_book: dict[str, Any],
    trades: list[dict[str, Any]],
    fundings: list[dict[str, Any]],
    candles: list[dict[str, Any]],
    collected_at: str,
) -> dict[str, Any]:
    market_id = str(details.get("id") or details.get("market_id") or "")
    best_bid, best_ask = _extract_best_levels(order_book)

    latest_funding = _latest_funding(fundings)

    normalized_trades = []
    for t in trades:
        normalized_trades.append(
            {
                "trade_id": str(t.get("trade_id") or t.get("id") or ""),
                "exchange_ts": ms_to_iso8601(
                    t.get("timestamp") or t.get("ts") or t.get("transaction_time")
                ),
                "price": to_float(t.get("price")),
                "size": to_float(t.get("size") or t.get("base_amount")),
                "side": str(t.get("side") or t.get("direction") or "").lower() or None,
                "is_liquidation": 1 if t.get("is_liquidation") else 0,
                "raw_json": json.dumps(t, ensure_ascii=True),
            }
        )

    normalized_fundings = []
    for f in fundings:
        normalized_fundings.append(
            {
                "exchange_ts": ms_to_iso8601(f.get("timestamp") or f.get("funding_timestamp")),
                "funding_rate": to_float(
                    f.get("funding_rate") or f.get("current_funding_rate") or f.get("rate") or f.get("value")
                ),
                "mark_price": to_float(f.get("mark_price")),
                "index_price": to_float(f.get("index_price")),
                "raw_json": json.dumps(f, ensure_ascii=True),
            }
        )

    normalized_candles = []
    for c in candles:
        normalized_candles.append(
            {
                "exchange_ts": ms_to_iso8601(c.get("timestamp") or c.get("t")),
                "resolution": str(c.get("resolution") or c.get("r") or "1m"),
                "open": to_float(c.get("open") or c.get("o") or c.get("O")),
                "high": to_float(c.get("high") or c.get("h") or c.get("H")),
                "low": to_float(c.get("low") or c.get("l") or c.get("L")),
                "close": to_float(c.get("close") or c.get("c") or c.get("C")),
                "volume": to_float(c.get("volume") or c.get("v") or c.get("V")),
                "raw_json": json.dumps(c, ensure_ascii=True),
            }
        )

    return {
        "instrument": {
            "exchange": "lighter",
            "market_id": market_id,
            "symbol": str(details.get("symbol") or details.get("name") or market_id),
            "base_asset": str(details.get("base") or details.get("base_asset") or details.get("base_symbol") or ""),
            "quote_asset": str(details.get("quote") or details.get("quote_asset") or details.get("quote_symbol") or "USDC"),
            "status": str(details.get("status") or "UNKNOWN").upper(),
            "instrument_type": "perp",
            "price_decimals": details.get("price_decimals"),
            "size_decimals": details.get("size_decimals"),
            "min_size": to_float(details.get("min_base_amount")),
            "raw_json": json.dumps(details, ensure_ascii=True),
        },
        "fees": {
            "maker_fee": to_float(details.get("maker_fee")),
            "taker_fee": to_float(details.get("taker_fee")),
            "fee_ccy": str(details.get("quote") or details.get("quote_asset") or "USDC"),
            "effective_at": collected_at,
            "raw_json": json.dumps(
                {
                    "maker_fee": details.get("maker_fee"),
                    "taker_fee": details.get("taker_fee"),
                },
                ensure_ascii=True,
            ),
        },
        "snapshot": {
            "collected_at": collected_at,
            "exchange_ts": ms_to_iso8601(order_book.get("timestamp")),
            "best_bid": best_bid,
            "best_ask": best_ask,
            "mark_price": to_float(latest_funding.get("mark_price")),
            "index_price": to_float(latest_funding.get("index_price")),
            "funding_rate": _extract_funding_rate(latest_funding),
            "funding_interval_sec": 3600,
            "open_interest_long": None,
            "open_interest_short": None,
            "volume_24h": None,
            "raw_json": json.dumps(order_book, ensure_ascii=True),
        },
        "orderbook": {
            "exchange_ts": ms_to_iso8601(order_book.get("timestamp")),
            "depth": len(order_book.get("asks") or []) + len(order_book.get("bids") or []),
            "raw_json": json.dumps(order_book, ensure_ascii=True),
        },
        "trades": normalized_trades,
        "fundings": normalized_fundings,
        "candles": normalized_candles,
    }


class LighterCollector:
    def __init__(self, client: LighterClient | None = None):
        self.client = client or LighterClient()

    def collect(self, market_ids: list[int] | None = None) -> list[dict[str, Any]]:
        logger.info("lighter fetch orderBookDetails")
        details = self.client.get_order_book_details()
        collected_at = now_iso8601()

        selected = []
        for d in details:
            if not isinstance(d, dict):
                continue
            market_id = d.get("id") or d.get("market_id")
            if market_id is None:
                continue
            if market_ids and int(market_id) not in market_ids:
                continue
            selected.append(d)
        logger.info("lighter selected markets=%d", len(selected))

        bundles: list[dict[str, Any]] = []
        for d in selected:
            mid = int(d.get("id") or d.get("market_id"))
            logger.info("lighter market_id=%d fetch orderbook", mid)
            order_book = self.client.get_order_book_orders(mid, limit=250)
            logger.info("lighter market_id=%d fetch trades", mid)
            trades = self.client.get_recent_trades(mid, limit=200)
            logger.info("lighter market_id=%d fetch fundings", mid)
            fundings = self.client.get_fundings(mid, resolution="1h", count_back=200)
            logger.info("lighter market_id=%d fetch candles", mid)
            candles = self.client.get_candles(mid, resolution="1m", count_back=300)
            bundles.append(
                normalize_lighter_market_bundle(
                    details=d,
                    order_book=order_book,
                    trades=trades,
                    fundings=fundings,
                    candles=candles,
                    collected_at=collected_at,
                )
            )
            logger.info(
                "lighter market_id=%d collected orderbook_asks=%d orderbook_bids=%d trades=%d fundings=%d candles=%d",
                mid,
                len(order_book.get("asks") or []),
                len(order_book.get("bids") or []),
                len(trades),
                len(fundings),
                len(candles),
            )
        return bundles
