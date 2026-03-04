from exchange_monitor.collectors.lighter_collector import normalize_lighter_market_bundle
from exchange_monitor.collectors.omni_collector import normalize_omni_listing


def test_normalize_omni_listing_maps_public_fields():
    listing = {
        "ticker": "DUSK",
        "name": "Dusk Perp",
        "mark_price": "0.1234",
        "funding_rate": "0.0001",
        "funding_interval_s": 3600,
        "quotes": {
            "updated_at": "2026-03-04T00:00:00Z",
            "base": {"bid": "0.1233", "ask": "0.1235"},
            "size_1k": {"bid": "0.1232", "ask": "0.1236"},
            "size_100k": {"bid": "0.1220", "ask": "0.1240"},
        },
        "open_interest": {
            "long_open_interest": "1000",
            "short_open_interest": "900",
        },
        "volume_24h": "99999",
    }

    normalized = normalize_omni_listing(listing, "2026-03-04T00:00:05Z")

    assert normalized["instrument"]["symbol"] == "DUSK"
    assert normalized["snapshot"]["best_bid"] == 0.1233
    assert normalized["snapshot"]["best_ask"] == 0.1235
    assert normalized["snapshot"]["mark_price"] == 0.1234
    assert normalized["snapshot"]["funding_rate"] == 0.0001
    assert normalized["snapshot"]["volume_24h"] == 99999.0
    assert len(normalized["quote_ladder"]) == 2
    assert normalized["quote_ladder"][0]["tier"] == "size_1k"


def test_normalize_lighter_market_bundle_maps_public_fields():
    details = {
        "id": 125,
        "symbol": "DUSK-PERP",
        "status": "ACTIVE",
        "base": "DUSK",
        "quote": "USDC",
        "price_decimals": 4,
        "size_decimals": 0,
        "min_base_amount": "1",
        "default_initial_margin_fraction": "0.1",
        "default_maintenance_margin_fraction": "0.05",
        "maker_fee": "0.0000",
        "taker_fee": "0.0000",
    }
    order_book = {
        "asks": [["0.1250", "100"]],
        "bids": [["0.1249", "80"]],
        "timestamp": 1700000000000,
    }
    trades = [
        {
            "trade_id": "t1",
            "price": "0.12495",
            "size": "50",
            "side": "buy",
            "timestamp": 1700000001000,
        }
    ]
    fundings = [
        {
            "timestamp": 1700000000000,
            "funding_rate": "0.0002",
            "mark_price": "0.12497",
            "index_price": "0.12490",
        }
    ]
    candles = [
        {
            "timestamp": 1700000000000,
            "open": "0.1200",
            "high": "0.1300",
            "low": "0.1100",
            "close": "0.1240",
            "volume": "100000",
            "resolution": "1m",
        }
    ]

    normalized = normalize_lighter_market_bundle(
        details=details,
        order_book=order_book,
        trades=trades,
        fundings=fundings,
        candles=candles,
        collected_at="2026-03-04T00:00:05Z",
    )

    assert normalized["instrument"]["market_id"] == "125"
    assert normalized["instrument"]["symbol"] == "DUSK-PERP"
    assert normalized["fees"]["maker_fee"] == 0.0
    assert normalized["snapshot"]["best_bid"] == 0.1249
    assert normalized["snapshot"]["best_ask"] == 0.1250
    assert normalized["trades"][0]["trade_id"] == "t1"
    assert normalized["fundings"][0]["funding_rate"] == 0.0002
    assert normalized["candles"][0]["resolution"] == "1m"


def test_normalize_lighter_snapshot_funding_rate_fallback_to_rate_or_value():
    details = {
        "market_id": 125,
        "symbol": "DUSK-PERP",
        "status": "ACTIVE",
        "base": "DUSK",
        "quote": "USDC",
        "price_decimals": 4,
        "size_decimals": 0,
        "min_base_amount": "1",
        "maker_fee": "0.0000",
        "taker_fee": "0.0000",
    }
    order_book = {
        "asks": [{"price": "0.1250"}],
        "bids": [{"price": "0.1249"}],
        "timestamp": 1700000000000,
    }
    # Intentionally use only `rate` and `value` from funding payload.
    fundings = [
        {"timestamp": 1700000000, "value": "0.00001"},
        {"timestamp": 1700003600, "rate": "0.0269"},
    ]

    normalized = normalize_lighter_market_bundle(
        details=details,
        order_book=order_book,
        trades=[],
        fundings=fundings,
        candles=[],
        collected_at="2026-03-04T00:00:05Z",
    )

    assert normalized["snapshot"]["funding_rate"] == 0.0269
