import sqlite3

from exchange_monitor.db.repository import Repository
from exchange_monitor.db.schema import create_schema


def test_repository_upsert_and_insert_timeseries():
    conn = sqlite3.connect(":memory:")
    create_schema(conn)
    repo = Repository(conn)

    instrument_id = repo.upsert_instrument(
        {
            "exchange": "lighter",
            "market_id": "125",
            "symbol": "DUSK-PERP",
            "base_asset": "DUSK",
            "quote_asset": "USDC",
            "status": "ACTIVE",
            "instrument_type": "perp",
            "price_decimals": 4,
            "size_decimals": 0,
            "min_size": 1.0,
            "raw_json": "{}",
        }
    )
    assert instrument_id > 0

    same_instrument_id = repo.upsert_instrument(
        {
            "exchange": "lighter",
            "market_id": "125",
            "symbol": "DUSK-PERP",
            "base_asset": "DUSK",
            "quote_asset": "USDC",
            "status": "ACTIVE",
            "instrument_type": "perp",
            "price_decimals": 5,
            "size_decimals": 0,
            "min_size": 1.0,
            "raw_json": "{}",
        }
    )
    assert same_instrument_id == instrument_id

    repo.insert_market_snapshot(
        {
            "instrument_id": instrument_id,
            "collected_at": "2026-03-04T00:00:00Z",
            "exchange_ts": "2026-03-04T00:00:00Z",
            "best_bid": 0.1,
            "best_ask": 0.2,
            "mark_price": 0.15,
            "index_price": None,
            "funding_rate": 0.001,
            "funding_interval_sec": 3600,
            "open_interest_long": 10,
            "open_interest_short": 8,
            "volume_24h": 99,
            "raw_json": "{}",
        }
    )

    repo.insert_trade(
        {
            "instrument_id": instrument_id,
            "trade_id": "t1",
            "exchange_ts": "2026-03-04T00:00:01Z",
            "price": 0.11,
            "size": 5,
            "side": "buy",
            "is_liquidation": 0,
            "raw_json": "{}",
        }
    )
    repo.insert_trade(
        {
            "instrument_id": instrument_id,
            "trade_id": "t1",
            "exchange_ts": "2026-03-04T00:00:01Z",
            "price": 0.11,
            "size": 5,
            "side": "buy",
            "is_liquidation": 0,
            "raw_json": "{}",
        }
    )

    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM instruments")
    assert cur.fetchone()[0] == 1

    cur.execute("SELECT price_decimals FROM instruments WHERE id = ?", (instrument_id,))
    assert cur.fetchone()[0] == 5

    cur.execute("SELECT COUNT(*) FROM trades")
    assert cur.fetchone()[0] == 1
