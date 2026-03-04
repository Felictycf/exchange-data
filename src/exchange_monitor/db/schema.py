from __future__ import annotations

import sqlite3


DDL = """
CREATE TABLE IF NOT EXISTS instruments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exchange TEXT NOT NULL,
    market_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    base_asset TEXT,
    quote_asset TEXT,
    status TEXT,
    instrument_type TEXT,
    price_decimals INTEGER,
    size_decimals INTEGER,
    min_size REAL,
    raw_json TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE(exchange, market_id)
);

CREATE TABLE IF NOT EXISTS fees (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    instrument_id INTEGER NOT NULL,
    effective_at TEXT NOT NULL,
    maker_fee REAL,
    taker_fee REAL,
    fee_ccy TEXT,
    raw_json TEXT,
    UNIQUE(instrument_id, effective_at),
    FOREIGN KEY(instrument_id) REFERENCES instruments(id)
);

CREATE TABLE IF NOT EXISTS market_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    instrument_id INTEGER NOT NULL,
    collected_at TEXT NOT NULL,
    exchange_ts TEXT,
    best_bid REAL,
    best_ask REAL,
    mark_price REAL,
    index_price REAL,
    funding_rate REAL,
    funding_interval_sec INTEGER,
    open_interest_long REAL,
    open_interest_short REAL,
    volume_24h REAL,
    raw_json TEXT,
    FOREIGN KEY(instrument_id) REFERENCES instruments(id)
);

CREATE TABLE IF NOT EXISTS quote_ladder_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    instrument_id INTEGER NOT NULL,
    collected_at TEXT NOT NULL,
    exchange_ts TEXT,
    tier TEXT NOT NULL,
    bid REAL,
    ask REAL,
    raw_json TEXT,
    FOREIGN KEY(instrument_id) REFERENCES instruments(id)
);

CREATE TABLE IF NOT EXISTS orderbook_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    instrument_id INTEGER NOT NULL,
    collected_at TEXT NOT NULL,
    exchange_ts TEXT,
    depth INTEGER,
    raw_json TEXT,
    FOREIGN KEY(instrument_id) REFERENCES instruments(id)
);

CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    instrument_id INTEGER NOT NULL,
    trade_id TEXT NOT NULL,
    exchange_ts TEXT,
    price REAL,
    size REAL,
    side TEXT,
    is_liquidation INTEGER NOT NULL DEFAULT 0,
    raw_json TEXT,
    UNIQUE(instrument_id, trade_id),
    FOREIGN KEY(instrument_id) REFERENCES instruments(id)
);

CREATE TABLE IF NOT EXISTS fundings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    instrument_id INTEGER NOT NULL,
    exchange_ts TEXT NOT NULL,
    funding_rate REAL,
    mark_price REAL,
    index_price REAL,
    raw_json TEXT,
    UNIQUE(instrument_id, exchange_ts),
    FOREIGN KEY(instrument_id) REFERENCES instruments(id)
);

CREATE TABLE IF NOT EXISTS candles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    instrument_id INTEGER NOT NULL,
    exchange_ts TEXT NOT NULL,
    resolution TEXT NOT NULL,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume REAL,
    raw_json TEXT,
    UNIQUE(instrument_id, exchange_ts, resolution),
    FOREIGN KEY(instrument_id) REFERENCES instruments(id)
);

CREATE INDEX IF NOT EXISTS idx_snapshots_instrument_collected
ON market_snapshots(instrument_id, collected_at);

CREATE INDEX IF NOT EXISTS idx_trades_instrument_exchange_ts
ON trades(instrument_id, exchange_ts);

CREATE INDEX IF NOT EXISTS idx_candles_instrument_resolution_ts
ON candles(instrument_id, resolution, exchange_ts);
"""


def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(DDL)
    conn.commit()
