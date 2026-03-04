from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import sqlite3
import time
from dataclasses import dataclass
from typing import Any

import websockets
from websockets.exceptions import ConnectionClosedError

from exchange_monitor.clients.lighter_client import LighterClient
from exchange_monitor.collectors.utils import ms_to_iso8601, now_iso8601, to_float
from exchange_monitor.db.repository import Repository
from exchange_monitor.db.schema import create_schema

logger = logging.getLogger(__name__)

WS_URL = "wss://mainnet.zklighter.elliot.ai/stream?readonly=true"


@dataclass
class StreamConfig:
    db_path: str
    snapshot_interval_sec: float = 5.0
    reconnect_base_sec: int = 2
    reconnect_max_sec: int = 30
    market_ids: list[int] | None = None
    writer_max_batch: int = 500
    writer_flush_interval_ms: int = 50


class SqliteStreamWriter:
    def __init__(self, db_path: str, max_batch: int = 500, flush_interval_ms: int = 50):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.execute("PRAGMA synchronous=NORMAL;")
        create_schema(self.conn)
        self.repo = Repository(self.conn)
        self.queue: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue(maxsize=20000)
        self._running = True
        self.max_batch = max_batch
        self.flush_interval_sec = max(flush_interval_ms / 1000.0, 0.005)

    def close(self) -> None:
        self.repo.commit()
        self.conn.close()

    def upsert_market_definitions(self, details: list[dict[str, Any]]) -> dict[int, int]:
        instrument_ids: dict[int, int] = {}
        collected_at = now_iso8601()
        for d in details:
            mid_raw = d.get("id") or d.get("market_id")
            if mid_raw is None:
                continue
            mid = int(mid_raw)
            inst = {
                "exchange": "lighter",
                "market_id": str(mid),
                "symbol": str(d.get("symbol") or d.get("name") or mid),
                "base_asset": str(d.get("base") or d.get("base_asset") or d.get("base_symbol") or ""),
                "quote_asset": str(d.get("quote") or d.get("quote_asset") or d.get("quote_symbol") or "USDC"),
                "status": str(d.get("status") or "UNKNOWN").upper(),
                "instrument_type": "perp",
                "price_decimals": d.get("price_decimals"),
                "size_decimals": d.get("size_decimals"),
                "min_size": to_float(d.get("min_base_amount")),
                "raw_json": json.dumps(d, ensure_ascii=True),
            }
            iid = self.repo.upsert_instrument(inst)
            instrument_ids[mid] = iid

            self.repo.upsert_fee(
                {
                    "instrument_id": iid,
                    "effective_at": collected_at,
                    "maker_fee": to_float(d.get("maker_fee")),
                    "taker_fee": to_float(d.get("taker_fee")),
                    "fee_ccy": str(d.get("quote") or d.get("quote_asset") or "USDC"),
                    "raw_json": json.dumps(
                        {"maker_fee": d.get("maker_fee"), "taker_fee": d.get("taker_fee")},
                        ensure_ascii=True,
                    ),
                }
            )
        self.repo.commit()
        return instrument_ids

    async def enqueue(self, op: str, payload: dict[str, Any]) -> None:
        await self.queue.put((op, payload))

    async def run(self) -> None:
        batch: list[tuple[str, dict[str, Any]]] = []
        while self._running:
            item = await self.queue.get()
            batch.append(item)
            start = time.monotonic()
            while len(batch) < self.max_batch:
                if (time.monotonic() - start) >= self.flush_interval_sec:
                    break
                try:
                    batch.append(self.queue.get_nowait())
                except asyncio.QueueEmpty:
                    await asyncio.sleep(0.001)
                    if self.queue.empty():
                        break

            await asyncio.to_thread(self._flush_batch, batch)
            logger.debug("ws writer committed events=%d queue=%d", len(batch), self.queue.qsize())
            batch.clear()

    async def stop(self) -> None:
        self._running = False

    def _flush_batch(self, batch: list[tuple[str, dict[str, Any]]]) -> None:
        for op, payload in batch:
            if op == "snapshot":
                self.repo.insert_market_snapshot(payload)
            elif op == "orderbook":
                self.repo.insert_orderbook_snapshot(payload)
            elif op == "trade":
                self.repo.insert_trade(payload)
            elif op == "funding":
                self.repo.insert_funding(payload)
            elif op == "candle":
                self.repo.insert_candle(payload)
        self.repo.commit()


def _price_from_node(node: Any) -> float | None:
    if node is None:
        return None
    if isinstance(node, dict):
        return to_float(node.get("price") or node.get("p"))
    if isinstance(node, (list, tuple)) and node:
        return to_float(node[0])
    return to_float(node)


def _extract_ticker(payload: dict[str, Any]) -> tuple[float | None, float | None, str | None]:
    ask = _price_from_node(payload.get("ask") or payload.get("a"))
    bid = _price_from_node(payload.get("bid") or payload.get("b"))
    ts = ms_to_iso8601(payload.get("timestamp") or payload.get("ts") or payload.get("t"))
    return bid, ask, ts


def _extract_funding_rate(payload: dict[str, Any]) -> float | None:
    return to_float(
        payload.get("funding_rate")
        or payload.get("current_funding_rate")
        or payload.get("rate")
        or payload.get("value")
    )


async def run_lighter_ws_stream(config: StreamConfig) -> None:
    client = LighterClient()
    details = client.get_order_book_details()
    discovered_market_ids = [
        int(d.get("id") or d.get("market_id"))
        for d in details
        if (d.get("id") is not None or d.get("market_id") is not None)
    ]
    market_ids = config.market_ids or discovered_market_ids
    market_set = set(market_ids)
    details = [
        d
        for d in details
        if int(d.get("id") or d.get("market_id")) in market_set
    ]

    writer = SqliteStreamWriter(
        config.db_path,
        max_batch=config.writer_max_batch,
        flush_interval_ms=config.writer_flush_interval_ms,
    )
    instrument_ids = writer.upsert_market_definitions(details)

    writer_task = asyncio.create_task(writer.run())
    market_state: dict[int, dict[str, Any]] = {mid: {} for mid in market_ids}
    last_snapshot_emit: dict[int, float] = {mid: 0.0 for mid in market_ids}

    backoff = config.reconnect_base_sec
    reconnects = 0
    recv_count = 0
    enqueue_count = 0
    last_hb = time.monotonic()
    logger.info("lighter ws stream starting markets=%d", len(market_ids))

    try:
        while True:
            try:
                async with websockets.connect(
                    WS_URL,
                    ping_interval=15,
                    ping_timeout=60,
                    close_timeout=10,
                    max_queue=4000,
                ) as ws:
                    logger.info("lighter ws connected url=%s", WS_URL)
                    backoff = config.reconnect_base_sec

                    for mid in market_ids:
                        for prefix in ("ticker", "order_book", "trade", "market_stats"):
                            await ws.send(json.dumps({"type": "subscribe", "channel": f"{prefix}/{mid}"}))
                    logger.info("lighter ws subscriptions sent total=%d", len(market_ids) * 4)

                    async for raw in ws:
                        recv_count += 1
                        msg = json.loads(raw)
                        if not isinstance(msg, dict):
                            continue
                        msg_type = msg.get("type")
                        if msg_type in {"connected", "subscribed"}:
                            continue

                        channel = str(msg.get("channel") or "").replace(":", "/")
                        data = msg.get("data") if isinstance(msg.get("data"), dict) else msg
                        if not channel:
                            continue
                        parts = channel.split("/")
                        if len(parts) != 2:
                            continue

                        topic, mid_text = parts
                        try:
                            mid = int(mid_text)
                        except ValueError:
                            continue
                        instrument_id = instrument_ids.get(mid)
                        if instrument_id is None:
                            continue

                        now = time.time()
                        collected_at = now_iso8601()

                        if topic == "ticker":
                            if isinstance(msg.get("ticker"), dict):
                                data = msg["ticker"]
                            bid, ask, ex_ts = _extract_ticker(data)
                            state = market_state[mid]
                            state["best_bid"] = bid
                            state["best_ask"] = ask
                            state["exchange_ts"] = ex_ts
                            should_emit_snapshot = (
                                config.snapshot_interval_sec <= 0
                                or now - last_snapshot_emit[mid] >= config.snapshot_interval_sec
                            )
                            if should_emit_snapshot:
                                await writer.enqueue(
                                    "snapshot",
                                    {
                                        "instrument_id": instrument_id,
                                        "collected_at": collected_at,
                                        "exchange_ts": state.get("exchange_ts"),
                                        "best_bid": state.get("best_bid"),
                                        "best_ask": state.get("best_ask"),
                                        "mark_price": state.get("mark_price"),
                                        "index_price": state.get("index_price"),
                                        "funding_rate": state.get("funding_rate"),
                                        "funding_interval_sec": 3600,
                                        "open_interest_long": None,
                                        "open_interest_short": None,
                                        "volume_24h": None,
                                        "raw_json": json.dumps(data, ensure_ascii=True),
                                    },
                                )
                                enqueue_count += 1
                                last_snapshot_emit[mid] = now

                        elif topic == "order_book":
                            if isinstance(msg.get("order_book"), dict):
                                data = msg["order_book"]
                            asks = data.get("asks") or []
                            bids = data.get("bids") or []
                            await writer.enqueue(
                                "orderbook",
                                {
                                    "instrument_id": instrument_id,
                                    "collected_at": collected_at,
                                    "exchange_ts": ms_to_iso8601(
                                        msg.get("timestamp") or data.get("timestamp") or data.get("ts")
                                    ),
                                    "depth": len(asks) + len(bids),
                                    "raw_json": json.dumps(data, ensure_ascii=True),
                                },
                            )
                            enqueue_count += 1

                        elif topic == "trade":
                            if isinstance(msg.get("trades"), list):
                                trades = msg["trades"]
                            else:
                                trades = []
                            if isinstance(msg.get("liquidation_trades"), list):
                                trades.extend(msg["liquidation_trades"])
                            if not trades:
                                trades = data if isinstance(data, list) else [data]
                            for trade in trades:
                                if not isinstance(trade, dict):
                                    continue
                                trade_id = str(trade.get("trade_id") or trade.get("id") or "")
                                if not trade_id:
                                    continue
                                await writer.enqueue(
                                    "trade",
                                    {
                                        "instrument_id": instrument_id,
                                        "trade_id": trade_id,
                                        "exchange_ts": ms_to_iso8601(
                                            trade.get("timestamp")
                                            or trade.get("ts")
                                            or trade.get("transaction_time")
                                        ),
                                        "price": to_float(trade.get("price")),
                                        "size": to_float(trade.get("size") or trade.get("base_amount")),
                                        "side": str(trade.get("side") or trade.get("direction") or "").lower() or None,
                                        "is_liquidation": 1 if trade.get("is_liquidation") else 0,
                                        "raw_json": json.dumps(trade, ensure_ascii=True),
                                    },
                                )
                                enqueue_count += 1

                        elif topic == "market_stats":
                            if isinstance(msg.get("market_stats"), dict):
                                data = msg["market_stats"]
                            state = market_state[mid]
                            state["mark_price"] = to_float(data.get("mark_price"))
                            state["index_price"] = to_float(data.get("index_price"))
                            state["funding_rate"] = _extract_funding_rate(data)

                            fts = ms_to_iso8601(data.get("funding_timestamp") or data.get("timestamp") or data.get("ts"))
                            if fts and state.get("funding_rate") is not None:
                                await writer.enqueue(
                                    "funding",
                                    {
                                        "instrument_id": instrument_id,
                                        "exchange_ts": fts,
                                        "funding_rate": state.get("funding_rate"),
                                        "mark_price": state.get("mark_price"),
                                        "index_price": state.get("index_price"),
                                        "raw_json": json.dumps(data, ensure_ascii=True),
                                    },
                                )
                                enqueue_count += 1

                        now_mono = time.monotonic()
                        if now_mono - last_hb >= 5.0:
                            logger.info(
                                "ws heartbeat recv=%d enqueued=%d queue=%d reconnects=%d",
                                recv_count,
                                enqueue_count,
                                writer.queue.qsize(),
                                reconnects,
                            )
                            last_hb = now_mono
            except asyncio.CancelledError:
                raise
            except KeyboardInterrupt:
                logger.info("lighter ws stream interrupted by user")
                break
            except ConnectionClosedError as exc:
                reconnects += 1
                logger.warning("lighter ws disconnected (will reconnect) code=%s reason=%s", exc.code, exc.reason)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, config.reconnect_max_sec)
            except Exception as exc:
                reconnects += 1
                logger.exception("lighter ws disconnected, will reconnect error=%s", exc)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, config.reconnect_max_sec)
    finally:
        await writer.stop()
        await asyncio.sleep(1.2)
        writer_task.cancel()
        with contextlib.suppress(Exception):
            await writer_task
        writer.close()
        logger.info("lighter ws stream stopped")
