from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field


@dataclass
class ValidationReport:
    ok: bool
    checks: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def _count(conn: sqlite3.Connection, table: str, where: str = "", args: tuple = ()) -> int:
    sql = f"SELECT COUNT(*) FROM {table}"
    if where:
        sql += f" WHERE {where}"
    return int(conn.execute(sql, args).fetchone()[0])


def validate_database(db_path: str) -> ValidationReport:
    conn = sqlite3.connect(db_path)
    report = ValidationReport(ok=True)

    required_tables = [
        "instruments",
        "fees",
        "market_snapshots",
        "quote_ladder_snapshots",
        "orderbook_snapshots",
        "trades",
        "fundings",
        "candles",
    ]
    for table in required_tables:
        if _exists(conn, table):
            report.checks.append(f"table exists: {table}")
        else:
            report.ok = False
            report.checks.append(f"table missing: {table}")

    if not report.ok:
        conn.close()
        return report

    total_instruments = _count(conn, "instruments")
    report.checks.append(f"instruments rows={total_instruments}")
    if total_instruments == 0:
        report.ok = False
        report.checks.append("no data collected")
        conn.close()
        return report

    omni_count = _count(conn, "instruments", "exchange='omni'")
    lighter_count = _count(conn, "instruments", "exchange='lighter'")
    report.checks.append(f"omni instruments={omni_count}")
    report.checks.append(f"lighter instruments={lighter_count}")

    # Omni public requirements
    if omni_count > 0:
        omni_snap = _count(
            conn,
            "market_snapshots",
            "instrument_id IN (SELECT id FROM instruments WHERE exchange='omni')",
        )
        omni_ladder = _count(
            conn,
            "quote_ladder_snapshots",
            "instrument_id IN (SELECT id FROM instruments WHERE exchange='omni')",
        )
        omni_fee = _count(
            conn,
            "fees",
            "instrument_id IN (SELECT id FROM instruments WHERE exchange='omni')",
        )
        report.checks.append(f"omni snapshots={omni_snap}")
        report.checks.append(f"omni quote_ladder={omni_ladder}")
        report.checks.append(f"omni fees={omni_fee}")
        if omni_snap == 0 or omni_ladder == 0 or omni_fee == 0:
            report.ok = False
            report.checks.append("omni public required datasets incomplete")

    # Lighter public requirements
    if lighter_count > 0:
        lighter_snap = _count(
            conn,
            "market_snapshots",
            "instrument_id IN (SELECT id FROM instruments WHERE exchange='lighter')",
        )
        lighter_orderbook = _count(
            conn,
            "orderbook_snapshots",
            "instrument_id IN (SELECT id FROM instruments WHERE exchange='lighter')",
        )
        lighter_trades = _count(
            conn,
            "trades",
            "instrument_id IN (SELECT id FROM instruments WHERE exchange='lighter')",
        )
        lighter_fundings = _count(
            conn,
            "fundings",
            "instrument_id IN (SELECT id FROM instruments WHERE exchange='lighter')",
        )
        lighter_candles = _count(
            conn,
            "candles",
            "instrument_id IN (SELECT id FROM instruments WHERE exchange='lighter')",
        )
        lighter_fees = _count(
            conn,
            "fees",
            "instrument_id IN (SELECT id FROM instruments WHERE exchange='lighter')",
        )
        report.checks.extend(
            [
                f"lighter snapshots={lighter_snap}",
                f"lighter orderbook={lighter_orderbook}",
                f"lighter trades={lighter_trades}",
                f"lighter fundings={lighter_fundings}",
                f"lighter candles={lighter_candles}",
                f"lighter fees={lighter_fees}",
            ]
        )
        if min(
            lighter_snap, lighter_orderbook, lighter_trades, lighter_fundings, lighter_candles, lighter_fees
        ) == 0:
            report.ok = False
            report.checks.append("lighter public required datasets incomplete")

    # Data quality checks
    null_bid_ask = conn.execute(
        """
        SELECT COUNT(*) FROM market_snapshots
        WHERE best_bid IS NULL OR best_ask IS NULL
        """
    ).fetchone()[0]
    report.checks.append(f"snapshots missing bbo rows={null_bid_ask}")
    if null_bid_ask > 0:
        report.warnings.append("some snapshots have NULL best_bid/best_ask")

    null_funding_rate = conn.execute(
        "SELECT COUNT(*) FROM market_snapshots WHERE funding_rate IS NULL"
    ).fetchone()[0]
    report.checks.append(f"snapshots missing funding_rate rows={null_funding_rate}")
    if null_funding_rate > 0:
        report.warnings.append("some snapshots have NULL funding_rate (expected for limited endpoints)")

    conn.close()
    return report
