from __future__ import annotations

import argparse
import asyncio
import logging
import time
from datetime import UTC, datetime

from exchange_monitor.logging_utils import configure_logging
from exchange_monitor.run_state import set_run_id, snapshot_stats
from exchange_monitor.service import collect_public_data
from exchange_monitor.stream_lighter import StreamConfig, run_lighter_ws_stream
from exchange_monitor.validation import validate_database


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Collect public market data from Omni and Lighter into SQLite"
    )
    parser.add_argument("--db-path", default="market_data.sqlite", help="SQLite database path")
    parser.add_argument("--only-omni", action="store_true", help="Collect only Omni")
    parser.add_argument("--only-lighter", action="store_true", help="Collect only Lighter")
    parser.add_argument(
        "--lighter-market-id",
        type=int,
        action="append",
        default=None,
        help="Collect specific Lighter market_id (repeatable)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level",
    )
    parser.add_argument("--log-dir", default="logs", help="Directory to store log files")
    parser.add_argument("--run-id", default=None, help="Custom run id, default uses UTC timestamp")
    parser.add_argument(
        "--skip-validation",
        action="store_true",
        help="Skip SQLite completeness validation after collection",
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Run continuously (24x7) with a fixed interval between collection cycles",
    )
    parser.add_argument(
        "--interval-sec",
        type=int,
        default=60,
        help="Seconds to wait between cycles in --loop mode",
    )
    parser.add_argument(
        "--stream-lighter",
        action="store_true",
        help="Run enterprise-style continuous Lighter WebSocket ingestion (never-ending until interrupted)",
    )
    parser.add_argument(
        "--ws-snapshot-interval-sec",
        type=float,
        default=5.0,
        help="For --stream-lighter: min interval per market between market_snapshots writes (0 = every tick)",
    )
    parser.add_argument(
        "--stream-market-id",
        type=int,
        action="append",
        default=None,
        help="For --stream-lighter: limit WebSocket subscription to specific market_id (repeatable)",
    )
    parser.add_argument(
        "--ws-writer-max-batch",
        type=int,
        default=500,
        help="For --stream-lighter: max events per SQLite write batch",
    )
    parser.add_argument(
        "--ws-writer-flush-ms",
        type=int,
        default=50,
        help="For --stream-lighter: flush interval in milliseconds for SQLite writer",
    )
    return parser


def run_once(args: argparse.Namespace, run_id: str) -> None:
    set_run_id(run_id)
    log_path = configure_logging(args.log_level, args.log_dir)
    logger = logging.getLogger(__name__)
    logger.info("run started run_id=%s log_file=%s", run_id, log_path)

    collect_omni = True
    collect_lighter = True
    if args.only_omni:
        collect_lighter = False
    if args.only_lighter:
        collect_omni = False

    summary = collect_public_data(
        db_path=args.db_path,
        collect_omni=collect_omni,
        collect_lighter=collect_lighter,
        lighter_market_ids=args.lighter_market_id,
    )

    retry_stats = snapshot_stats()
    logger.info(
        "collection complete "
        f"instruments={summary.instruments} "
        f"snapshots={summary.snapshots} "
        f"trades={summary.trades} "
        f"fundings={summary.fundings} "
        f"candles={summary.candles} "
        f"requests={retry_stats.requests} "
        f"retries={retry_stats.retries} "
        f"failures={retry_stats.failures} "
        f"recovered={retry_stats.recovered}"
    )
    if retry_stats.retries_by_endpoint:
        logger.info("retry_by_endpoint=%s", dict(retry_stats.retries_by_endpoint))
    if retry_stats.failures_by_endpoint:
        logger.warning("failure_by_endpoint=%s", dict(retry_stats.failures_by_endpoint))

    if not args.skip_validation:
        report = validate_database(args.db_path)
        logger.info("sqlite validation result=%s", "PASS" if report.ok else "FAIL")
        for line in report.checks:
            logger.info("validation: %s", line)
        for line in report.warnings:
            logger.warning("validation warning: %s", line)


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.stream_lighter:
        run_id = args.run_id or datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
        set_run_id(run_id)
        log_path = configure_logging(args.log_level, args.log_dir)
        logger = logging.getLogger(__name__)
        logger.info("stream mode started run_id=%s log_file=%s", run_id, log_path)
        asyncio.run(
            run_lighter_ws_stream(
                StreamConfig(
                    db_path=args.db_path,
                    snapshot_interval_sec=args.ws_snapshot_interval_sec,
                    market_ids=args.stream_market_id,
                    writer_max_batch=args.ws_writer_max_batch,
                    writer_flush_interval_ms=args.ws_writer_flush_ms,
                )
            )
        )
        return

    if args.loop and args.interval_sec < 1:
        raise ValueError("--interval-sec must be >= 1")

    if not args.loop:
        run_once(args, args.run_id or datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ"))
        return

    cycle = 0
    while True:
        cycle += 1
        cycle_run_id = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
        args.run_id = cycle_run_id
        try:
            run_once(args, cycle_run_id)
        except KeyboardInterrupt:
            logging.getLogger(__name__).info("loop interrupted by user at cycle=%d", cycle)
            break
        except Exception as exc:
            logging.getLogger(__name__).exception(
                "loop cycle failed cycle=%d run_id=%s error=%s", cycle, cycle_run_id, exc
            )
        logging.getLogger(__name__).info(
            "sleeping before next cycle cycle=%d interval_sec=%d",
            cycle,
            args.interval_sec,
        )
        time.sleep(args.interval_sec)


if __name__ == "__main__":
    main()
