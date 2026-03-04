from __future__ import annotations

import sqlite3
from typing import Any


class Repository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def upsert_instrument(self, instrument: dict[str, Any]) -> int:
        self.conn.execute(
            """
            INSERT INTO instruments (
                exchange, market_id, symbol, base_asset, quote_asset, status,
                instrument_type, price_decimals, size_decimals, min_size, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(exchange, market_id) DO UPDATE SET
                symbol=excluded.symbol,
                base_asset=excluded.base_asset,
                quote_asset=excluded.quote_asset,
                status=excluded.status,
                instrument_type=excluded.instrument_type,
                price_decimals=excluded.price_decimals,
                size_decimals=excluded.size_decimals,
                min_size=excluded.min_size,
                raw_json=excluded.raw_json,
                updated_at=strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            """,
            (
                instrument.get("exchange"),
                instrument.get("market_id"),
                instrument.get("symbol"),
                instrument.get("base_asset"),
                instrument.get("quote_asset"),
                instrument.get("status"),
                instrument.get("instrument_type"),
                instrument.get("price_decimals"),
                instrument.get("size_decimals"),
                instrument.get("min_size"),
                instrument.get("raw_json"),
            ),
        )
        row = self.conn.execute(
            "SELECT id FROM instruments WHERE exchange = ? AND market_id = ?",
            (instrument.get("exchange"), instrument.get("market_id")),
        ).fetchone()
        assert row is not None
        return int(row[0])

    def upsert_fee(self, fee: dict[str, Any]) -> None:
        self.conn.execute(
            """
            INSERT INTO fees (instrument_id, effective_at, maker_fee, taker_fee, fee_ccy, raw_json)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(instrument_id, effective_at) DO UPDATE SET
                maker_fee=excluded.maker_fee,
                taker_fee=excluded.taker_fee,
                fee_ccy=excluded.fee_ccy,
                raw_json=excluded.raw_json
            """,
            (
                fee.get("instrument_id"),
                fee.get("effective_at"),
                fee.get("maker_fee"),
                fee.get("taker_fee"),
                fee.get("fee_ccy"),
                fee.get("raw_json"),
            ),
        )

    def insert_market_snapshot(self, snapshot: dict[str, Any]) -> None:
        self.conn.execute(
            """
            INSERT INTO market_snapshots (
                instrument_id, collected_at, exchange_ts, best_bid, best_ask,
                mark_price, index_price, funding_rate, funding_interval_sec,
                open_interest_long, open_interest_short, volume_24h, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot.get("instrument_id"),
                snapshot.get("collected_at"),
                snapshot.get("exchange_ts"),
                snapshot.get("best_bid"),
                snapshot.get("best_ask"),
                snapshot.get("mark_price"),
                snapshot.get("index_price"),
                snapshot.get("funding_rate"),
                snapshot.get("funding_interval_sec"),
                snapshot.get("open_interest_long"),
                snapshot.get("open_interest_short"),
                snapshot.get("volume_24h"),
                snapshot.get("raw_json"),
            ),
        )

    def insert_quote_ladder(self, item: dict[str, Any]) -> None:
        self.conn.execute(
            """
            INSERT INTO quote_ladder_snapshots (
                instrument_id, collected_at, exchange_ts, tier, bid, ask, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item.get("instrument_id"),
                item.get("collected_at"),
                item.get("exchange_ts"),
                item.get("tier"),
                item.get("bid"),
                item.get("ask"),
                item.get("raw_json"),
            ),
        )

    def insert_orderbook_snapshot(self, item: dict[str, Any]) -> None:
        self.conn.execute(
            """
            INSERT INTO orderbook_snapshots (instrument_id, collected_at, exchange_ts, depth, raw_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                item.get("instrument_id"),
                item.get("collected_at"),
                item.get("exchange_ts"),
                item.get("depth"),
                item.get("raw_json"),
            ),
        )

    def insert_trade(self, trade: dict[str, Any]) -> None:
        self.conn.execute(
            """
            INSERT OR IGNORE INTO trades (
                instrument_id, trade_id, exchange_ts, price, size, side, is_liquidation, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trade.get("instrument_id"),
                trade.get("trade_id"),
                trade.get("exchange_ts"),
                trade.get("price"),
                trade.get("size"),
                trade.get("side"),
                trade.get("is_liquidation", 0),
                trade.get("raw_json"),
            ),
        )

    def insert_funding(self, funding: dict[str, Any]) -> None:
        self.conn.execute(
            """
            INSERT OR IGNORE INTO fundings (
                instrument_id, exchange_ts, funding_rate, mark_price, index_price, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                funding.get("instrument_id"),
                funding.get("exchange_ts"),
                funding.get("funding_rate"),
                funding.get("mark_price"),
                funding.get("index_price"),
                funding.get("raw_json"),
            ),
        )

    def insert_candle(self, candle: dict[str, Any]) -> None:
        self.conn.execute(
            """
            INSERT OR IGNORE INTO candles (
                instrument_id, exchange_ts, resolution, open, high, low, close, volume, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                candle.get("instrument_id"),
                candle.get("exchange_ts"),
                candle.get("resolution"),
                candle.get("open"),
                candle.get("high"),
                candle.get("low"),
                candle.get("close"),
                candle.get("volume"),
                candle.get("raw_json"),
            ),
        )

    def commit(self) -> None:
        self.conn.commit()
