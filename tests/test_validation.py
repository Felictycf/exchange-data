import sqlite3

from exchange_monitor.db.repository import Repository
from exchange_monitor.db.schema import create_schema
from exchange_monitor.validation import validate_database


def _insert_minimal_public_data(conn: sqlite3.Connection) -> None:
    repo = Repository(conn)

    omni_id = repo.upsert_instrument(
        {
            "exchange": "omni",
            "market_id": "DUSK",
            "symbol": "DUSK",
            "base_asset": "DUSK",
            "quote_asset": "USD",
            "status": "ACTIVE",
            "instrument_type": "rfq_perp",
            "price_decimals": None,
            "size_decimals": None,
            "min_size": None,
            "raw_json": "{}",
        }
    )
    repo.upsert_fee(
        {
            "instrument_id": omni_id,
            "effective_at": "2026-03-04T00:00:00Z",
            "maker_fee": 0.0,
            "taker_fee": 0.0,
            "fee_ccy": "USD",
            "raw_json": "{}",
        }
    )
    repo.insert_market_snapshot(
        {
            "instrument_id": omni_id,
            "collected_at": "2026-03-04T00:00:00Z",
            "exchange_ts": "2026-03-04T00:00:00Z",
            "best_bid": 1.0,
            "best_ask": 1.1,
            "mark_price": 1.05,
            "index_price": None,
            "funding_rate": 0.0001,
            "funding_interval_sec": 3600,
            "open_interest_long": 10,
            "open_interest_short": 9,
            "volume_24h": 100,
            "raw_json": "{}",
        }
    )
    repo.insert_quote_ladder(
        {
            "instrument_id": omni_id,
            "collected_at": "2026-03-04T00:00:00Z",
            "exchange_ts": "2026-03-04T00:00:00Z",
            "tier": "size_1k",
            "bid": 1.0,
            "ask": 1.1,
            "raw_json": "{}",
        }
    )

    lighter_id = repo.upsert_instrument(
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
    repo.upsert_fee(
        {
            "instrument_id": lighter_id,
            "effective_at": "2026-03-04T00:00:00Z",
            "maker_fee": 0.0,
            "taker_fee": 0.0,
            "fee_ccy": "USDC",
            "raw_json": "{}",
        }
    )
    repo.insert_market_snapshot(
        {
            "instrument_id": lighter_id,
            "collected_at": "2026-03-04T00:00:00Z",
            "exchange_ts": "2026-03-04T00:00:00Z",
            "best_bid": 1.0,
            "best_ask": 1.1,
            "mark_price": 1.05,
            "index_price": 1.04,
            "funding_rate": 0.0002,
            "funding_interval_sec": 3600,
            "open_interest_long": None,
            "open_interest_short": None,
            "volume_24h": None,
            "raw_json": "{}",
        }
    )
    repo.insert_orderbook_snapshot(
        {
            "instrument_id": lighter_id,
            "collected_at": "2026-03-04T00:00:00Z",
            "exchange_ts": "2026-03-04T00:00:00Z",
            "depth": 10,
            "raw_json": "{}",
        }
    )
    repo.insert_trade(
        {
            "instrument_id": lighter_id,
            "trade_id": "t1",
            "exchange_ts": "2026-03-04T00:00:01Z",
            "price": 1.01,
            "size": 2,
            "side": "buy",
            "is_liquidation": 0,
            "raw_json": "{}",
        }
    )
    repo.insert_funding(
        {
            "instrument_id": lighter_id,
            "exchange_ts": "2026-03-04T00:00:00Z",
            "funding_rate": 0.0002,
            "mark_price": 1.05,
            "index_price": 1.04,
            "raw_json": "{}",
        }
    )
    repo.insert_candle(
        {
            "instrument_id": lighter_id,
            "exchange_ts": "2026-03-04T00:00:00Z",
            "resolution": "1m",
            "open": 1.0,
            "high": 1.1,
            "low": 0.9,
            "close": 1.05,
            "volume": 99,
            "raw_json": "{}",
        }
    )
    repo.commit()


def test_validation_passes_with_required_public_data(tmp_path):
    db_path = tmp_path / "ok.sqlite"
    conn = sqlite3.connect(db_path)
    create_schema(conn)
    _insert_minimal_public_data(conn)
    conn.close()

    report = validate_database(str(db_path))
    assert report.ok is True


def test_validation_fails_for_empty_db(tmp_path):
    db_path = tmp_path / "empty.sqlite"
    conn = sqlite3.connect(db_path)
    create_schema(conn)
    conn.close()

    report = validate_database(str(db_path))
    assert report.ok is False
