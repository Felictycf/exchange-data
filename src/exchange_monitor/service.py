from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass

from exchange_monitor.collectors.lighter_collector import LighterCollector
from exchange_monitor.collectors.omni_collector import OmniCollector
from exchange_monitor.collectors.utils import now_iso8601
from exchange_monitor.db.repository import Repository
from exchange_monitor.db.schema import create_schema

logger = logging.getLogger(__name__)


@dataclass
class CollectionSummary:
    instruments: int = 0
    snapshots: int = 0
    trades: int = 0
    fundings: int = 0
    candles: int = 0


def collect_public_data(
    db_path: str,
    collect_omni: bool = True,
    collect_lighter: bool = True,
    lighter_market_ids: list[int] | None = None,
) -> CollectionSummary:
    logger.info(
        "start collection db_path=%s omni=%s lighter=%s lighter_market_ids=%s",
        db_path,
        collect_omni,
        collect_lighter,
        lighter_market_ids,
    )
    conn = sqlite3.connect(db_path)
    create_schema(conn)
    repo = Repository(conn)
    summary = CollectionSummary()

    if collect_omni:
        logger.info("collecting omni public data")
        omni = OmniCollector()
        omni_items = omni.collect()
        logger.info("omni listings fetched count=%d", len(omni_items))
        for idx, item in enumerate(omni_items, start=1):
            symbol = item["instrument"].get("symbol")
            if idx == 1 or idx % 50 == 0 or idx == len(omni_items):
                logger.info("omni progress %d/%d symbol=%s", idx, len(omni_items), symbol)
            instrument_id = repo.upsert_instrument(item["instrument"])
            summary.instruments += 1

            fee = {"instrument_id": instrument_id, **item["fees"]}
            repo.upsert_fee(fee)

            snapshot = {"instrument_id": instrument_id, **item["snapshot"]}
            repo.insert_market_snapshot(snapshot)
            summary.snapshots += 1

            for q in item.get("quote_ladder", []):
                repo.insert_quote_ladder({"instrument_id": instrument_id, **q})
        logger.info("omni collection finished snapshots=%d", len(omni_items))

    if collect_lighter:
        logger.info("collecting lighter public data")
        lighter = LighterCollector()
        lighter_items = lighter.collect(market_ids=lighter_market_ids)
        logger.info("lighter markets fetched count=%d", len(lighter_items))
        for idx, item in enumerate(lighter_items, start=1):
            symbol = item["instrument"].get("symbol")
            market_id = item["instrument"].get("market_id")
            logger.info(
                "lighter market %d/%d market_id=%s symbol=%s trades=%d fundings=%d candles=%d",
                idx,
                len(lighter_items),
                market_id,
                symbol,
                len(item.get("trades", [])),
                len(item.get("fundings", [])),
                len(item.get("candles", [])),
            )
            instrument_id = repo.upsert_instrument(item["instrument"])
            summary.instruments += 1

            fee = {"instrument_id": instrument_id, **item["fees"]}
            repo.upsert_fee(fee)

            snapshot = {"instrument_id": instrument_id, **item["snapshot"]}
            repo.insert_market_snapshot(snapshot)
            summary.snapshots += 1

            orderbook = {"instrument_id": instrument_id, "collected_at": now_iso8601(), **item["orderbook"]}
            repo.insert_orderbook_snapshot(orderbook)

            for t in item.get("trades", []):
                repo.insert_trade({"instrument_id": instrument_id, **t})
                summary.trades += 1
            for f in item.get("fundings", []):
                if f.get("exchange_ts"):
                    repo.insert_funding({"instrument_id": instrument_id, **f})
                    summary.fundings += 1
            for c in item.get("candles", []):
                if c.get("exchange_ts") and c.get("resolution"):
                    repo.insert_candle({"instrument_id": instrument_id, **c})
                    summary.candles += 1
        logger.info("lighter collection finished markets=%d", len(lighter_items))

    repo.commit()
    conn.close()
    logger.info(
        "collection committed instruments=%d snapshots=%d trades=%d fundings=%d candles=%d",
        summary.instruments,
        summary.snapshots,
        summary.trades,
        summary.fundings,
        summary.candles,
    )
    return summary
