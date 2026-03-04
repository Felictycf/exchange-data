from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import sqlite3
import time
from dataclasses import dataclass
from collections import deque
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
    ws_shards: int = 4
    queue_drop_threshold: int = 15000


@dataclass
class StreamMetrics:
    recv_count: int = 0
    enqueued_count: int = 0
    reconnects: int = 0
    dropped_orderbook: int = 0
    dropped_snapshot: int = 0


class RollingLatency:
    """Fixed-size rolling latency samples with percentile summary."""

    def __init__(self, maxlen: int = 20000):
        self.samples: deque[float] = deque(maxlen=maxlen)

    def add(self, value_ms: float | None) -> None:
        if value_ms is None:
            return
        if value_ms < 0:
            return
        # Drop clearly invalid/outlier clocks to keep metrics meaningful.
        if value_ms > 3_600_000:
            return
        self.samples.append(float(value_ms))

    def count(self) -> int:
        return len(self.samples)

    def p(self, q: float) -> float | None:
        if not self.samples:
            return None
        arr = sorted(self.samples)
        idx = int((len(arr) - 1) * q)
        return arr[idx]

    def summary(self) -> str:
        if not self.samples:
            return "n=0"
        p50 = self.p(0.50)
        p95 = self.p(0.95)
        p99 = self.p(0.99)
        return f"n={self.count()} p50={p50:.1f}ms p95={p95:.1f}ms p99={p99:.1f}ms"


class LatencyBook:
    def __init__(self):
        self.exchange_to_recv_ms = RollingLatency()
        self.recv_to_enqueue_ms = RollingLatency()
        self.queue_to_commit_ms = RollingLatency()
        self.batch_commit_ms = RollingLatency(maxlen=5000)


class SqliteStreamWriter:
    def __init__(self, db_path: str, max_batch: int = 500, flush_interval_ms: int = 50):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.execute("PRAGMA synchronous=NORMAL;")
        self.conn.execute("PRAGMA temp_store=MEMORY;")
        self.conn.execute("PRAGMA cache_size=-200000;")
        create_schema(self.conn)
        self.repo = Repository(self.conn)
        self.queue: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue(maxsize=50000)
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

    async def enqueue(self, op: str, payload: dict[str, Any], enqueue_mono: float) -> None:
        await self.queue.put((op, payload, enqueue_mono))

    async def run(self, latency_book: LatencyBook) -> None:
        batch: list[tuple[str, dict[str, Any], float]] = []
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

            flush_start = time.monotonic()
            for _, _, enq_mono in batch:
                latency_book.queue_to_commit_ms.add((flush_start - enq_mono) * 1000.0)
            await asyncio.to_thread(self._flush_batch, batch)
            flush_end = time.monotonic()
            latency_book.batch_commit_ms.add((flush_end - flush_start) * 1000.0)
            logger.debug("ws writer committed events=%d queue=%d", len(batch), self.queue.qsize())
            batch.clear()

    async def stop(self) -> None:
        self._running = False

    def _flush_batch(self, batch: list[tuple[str, dict[str, Any], float]]) -> None:
        for op, payload, _ in batch:
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


def _extract_ticker(payload: dict[str, Any], msg: dict[str, Any]) -> tuple[float | None, float | None, str | None]:
    ask = _price_from_node(payload.get("ask") or payload.get("a"))
    bid = _price_from_node(payload.get("bid") or payload.get("b"))
    ts = ms_to_iso8601(payload.get("timestamp") or payload.get("ts") or payload.get("t") or msg.get("timestamp"))
    return bid, ask, ts


def _extract_funding_rate(payload: dict[str, Any]) -> float | None:
    return to_float(
        payload.get("funding_rate")
        or payload.get("current_funding_rate")
        or payload.get("rate")
        or payload.get("value")
    )


def _extract_exchange_ts_ms(topic: str, msg: dict[str, Any], data: dict[str, Any], trade: dict[str, Any] | None = None) -> int | None:
    try:
        if topic == "order_book":
            ts = msg.get("timestamp") or data.get("timestamp") or data.get("ts")
        elif topic == "trade" and trade is not None:
            ts = trade.get("timestamp") or trade.get("ts") or trade.get("transaction_time")
        elif topic == "ticker":
            ts = msg.get("timestamp") or data.get("timestamp") or data.get("ts") or data.get("t")
        elif topic == "market_stats":
            ts = msg.get("timestamp") or data.get("timestamp") or data.get("ts")
        else:
            ts = None
        if ts is None:
            return None
        ts_int = int(ts)
        if ts_int < 10_000_000_000:
            ts_int *= 1000
        return ts_int
    except (TypeError, ValueError):
        return None


def _is_realtime_latency_sample(msg_type: str | None, recv_wall_ms: int, exch_ts_ms: int | None) -> bool:
    """Only use real-time update messages for exchange->recv latency metrics."""
    if exch_ts_ms is None:
        return False
    if not msg_type or not msg_type.startswith("update/"):
        return False
    # Discard stale or clock-skewed samples from historical/backfill payloads.
    delta = recv_wall_ms - exch_ts_ms
    return -10_000 <= delta <= 120_000


def _shard_markets(market_ids: list[int], shard_count: int) -> list[list[int]]:
    if shard_count <= 1:
        return [market_ids]
    shards: list[list[int]] = [[] for _ in range(shard_count)]
    for idx, mid in enumerate(market_ids):
        shards[idx % shard_count].append(mid)
    return [s for s in shards if s]


async def _subscribe_shard(ws: websockets.WebSocketClientProtocol, mids: list[int]) -> None:
    for mid in mids:
        for prefix in ("ticker", "order_book", "trade", "market_stats"):
            await ws.send(json.dumps({"type": "subscribe", "channel": f"{prefix}/{mid}"}))


async def _run_ws_shard(
    shard_id: int,
    mids: list[int],
    config: StreamConfig,
    writer: SqliteStreamWriter,
    instrument_ids: dict[int, int],
    metrics: StreamMetrics,
    latency_book: LatencyBook,
    stop_event: asyncio.Event,
) -> None:
    market_state: dict[int, dict[str, Any]] = {mid: {} for mid in mids}
    last_snapshot_emit: dict[int, float] = {mid: 0.0 for mid in mids}
    backoff = config.reconnect_base_sec

    logger.info("lighter ws shard start shard=%d markets=%d", shard_id, len(mids))

    while not stop_event.is_set():
        try:
            async with websockets.connect(
                WS_URL,
                ping_interval=15,
                ping_timeout=60,
                close_timeout=10,
                max_queue=4000,
                compression=None,
            ) as ws:
                logger.info("lighter ws connected shard=%d url=%s", shard_id, WS_URL)
                await _subscribe_shard(ws, mids)
                logger.info("lighter ws subscriptions sent shard=%d total=%d", shard_id, len(mids) * 4)
                backoff = config.reconnect_base_sec

                async for raw in ws:
                    metrics.recv_count += 1
                    recv_mono = time.monotonic()
                    recv_wall_ms = int(time.time() * 1000)
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
                    qsize = writer.queue.qsize()

                    if topic == "ticker":
                        if isinstance(msg.get("ticker"), dict):
                            data = msg["ticker"]
                        exch_ts_ms = _extract_exchange_ts_ms(topic, msg, data)
                        if _is_realtime_latency_sample(msg_type, recv_wall_ms, exch_ts_ms):
                            latency_book.exchange_to_recv_ms.add(recv_wall_ms - exch_ts_ms)
                        bid, ask, ex_ts = _extract_ticker(data, msg)
                        state = market_state[mid]
                        state["best_bid"] = bid
                        state["best_ask"] = ask
                        state["exchange_ts"] = ex_ts
                        should_emit_snapshot = (
                            config.snapshot_interval_sec <= 0
                            or now - last_snapshot_emit[mid] >= config.snapshot_interval_sec
                        )
                        if should_emit_snapshot:
                            if qsize > config.queue_drop_threshold:
                                metrics.dropped_snapshot += 1
                            else:
                                t0 = time.monotonic()
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
                                    enqueue_mono=t0,
                                )
                                metrics.enqueued_count += 1
                                latency_book.recv_to_enqueue_ms.add((time.monotonic() - recv_mono) * 1000.0)
                                last_snapshot_emit[mid] = now

                    elif topic == "order_book":
                        if isinstance(msg.get("order_book"), dict):
                            data = msg["order_book"]
                        exch_ts_ms = _extract_exchange_ts_ms(topic, msg, data)
                        if _is_realtime_latency_sample(msg_type, recv_wall_ms, exch_ts_ms):
                            latency_book.exchange_to_recv_ms.add(recv_wall_ms - exch_ts_ms)
                        asks = data.get("asks") or []
                        bids = data.get("bids") or []
                        if qsize > config.queue_drop_threshold:
                            metrics.dropped_orderbook += 1
                        else:
                            t0 = time.monotonic()
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
                                enqueue_mono=t0,
                            )
                            metrics.enqueued_count += 1
                            latency_book.recv_to_enqueue_ms.add((time.monotonic() - recv_mono) * 1000.0)

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
                            exch_ts_ms = _extract_exchange_ts_ms(topic, msg, data, trade=trade)
                            if _is_realtime_latency_sample(msg_type, recv_wall_ms, exch_ts_ms):
                                latency_book.exchange_to_recv_ms.add(recv_wall_ms - exch_ts_ms)
                            t0 = time.monotonic()
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
                                enqueue_mono=t0,
                            )
                            metrics.enqueued_count += 1
                            latency_book.recv_to_enqueue_ms.add((time.monotonic() - recv_mono) * 1000.0)

                    elif topic == "market_stats":
                        if isinstance(msg.get("market_stats"), dict):
                            data = msg["market_stats"]
                        exch_ts_ms = _extract_exchange_ts_ms(topic, msg, data)
                        if _is_realtime_latency_sample(msg_type, recv_wall_ms, exch_ts_ms):
                            latency_book.exchange_to_recv_ms.add(recv_wall_ms - exch_ts_ms)
                        state = market_state[mid]
                        state["mark_price"] = to_float(data.get("mark_price"))
                        state["index_price"] = to_float(data.get("index_price"))
                        state["funding_rate"] = _extract_funding_rate(data)

                        fts = ms_to_iso8601(data.get("funding_timestamp") or data.get("timestamp") or data.get("ts"))
                        if fts and state.get("funding_rate") is not None:
                            t0 = time.monotonic()
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
                                enqueue_mono=t0,
                            )
                            metrics.enqueued_count += 1
                            latency_book.recv_to_enqueue_ms.add((time.monotonic() - recv_mono) * 1000.0)

        except asyncio.CancelledError:
            raise
        except ConnectionClosedError as exc:
            metrics.reconnects += 1
            logger.warning(
                "lighter ws disconnected shard=%d (will reconnect) code=%s reason=%s",
                shard_id,
                exc.code,
                exc.reason,
            )
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, config.reconnect_max_sec)
        except Exception as exc:
            metrics.reconnects += 1
            logger.exception("lighter ws shard error shard=%d error=%s", shard_id, exc)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, config.reconnect_max_sec)


async def _heartbeat_loop(
    writer: SqliteStreamWriter, metrics: StreamMetrics, latency_book: LatencyBook, stop_event: asyncio.Event
) -> None:
    while not stop_event.is_set():
        await asyncio.sleep(5)
        logger.info(
            "ws heartbeat recv=%d enqueued=%d queue=%d reconnects=%d dropped_orderbook=%d dropped_snapshot=%d "
            "lat_exch_recv[%s] lat_recv_enq[%s] lat_queue_commit[%s] lat_batch_commit[%s]",
            metrics.recv_count,
            metrics.enqueued_count,
            writer.queue.qsize(),
            metrics.reconnects,
            metrics.dropped_orderbook,
            metrics.dropped_snapshot,
            latency_book.exchange_to_recv_ms.summary(),
            latency_book.recv_to_enqueue_ms.summary(),
            latency_book.queue_to_commit_ms.summary(),
            latency_book.batch_commit_ms.summary(),
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
    details = [d for d in details if int(d.get("id") or d.get("market_id")) in market_set]

    writer = SqliteStreamWriter(
        config.db_path,
        max_batch=config.writer_max_batch,
        flush_interval_ms=config.writer_flush_interval_ms,
    )
    instrument_ids = writer.upsert_market_definitions(details)

    metrics = StreamMetrics()
    latency_book = LatencyBook()
    stop_event = asyncio.Event()

    writer_task = asyncio.create_task(writer.run(latency_book))
    heartbeat_task = asyncio.create_task(_heartbeat_loop(writer, metrics, latency_book, stop_event))

    shard_count = max(1, min(config.ws_shards, len(market_ids)))
    market_shards = _shard_markets(market_ids, shard_count)
    shard_tasks = [
        asyncio.create_task(
            _run_ws_shard(
                shard_id=i,
                mids=shard,
                config=config,
                writer=writer,
                instrument_ids=instrument_ids,
                metrics=metrics,
                latency_book=latency_book,
                stop_event=stop_event,
            )
        )
        for i, shard in enumerate(market_shards, start=1)
    ]

    logger.info("lighter ws stream starting markets=%d shards=%d", len(market_ids), len(shard_tasks))

    try:
        await asyncio.gather(*shard_tasks)
    except KeyboardInterrupt:
        logger.info("lighter ws stream interrupted by user")
    finally:
        stop_event.set()
        for task in shard_tasks:
            task.cancel()
        heartbeat_task.cancel()
        await writer.stop()
        await asyncio.sleep(0.5)
        writer_task.cancel()
        with contextlib.suppress(Exception):
            await asyncio.gather(*shard_tasks, return_exceptions=True)
        with contextlib.suppress(Exception):
            await heartbeat_task
        with contextlib.suppress(Exception):
            await writer_task
        writer.close()
        logger.info("lighter ws stream stopped")
