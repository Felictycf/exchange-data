from __future__ import annotations

import logging
from pathlib import Path

from exchange_monitor.run_state import get_run_id


class RunIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.run_id = get_run_id()
        return True


def configure_logging(level: str, log_dir: str) -> str:
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    run_id = get_run_id()
    log_path = str(Path(log_dir) / f"collector-{run_id}.log")

    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper()))
    root.handlers.clear()

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s [run_id=%(run_id)s] %(name)s: %(message)s"
    )
    run_filter = RunIdFilter()

    console = logging.StreamHandler()
    console.setLevel(getattr(logging, level.upper()))
    console.setFormatter(formatter)
    console.addFilter(run_filter)

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    file_handler.addFilter(run_filter)

    root.addHandler(console)
    root.addHandler(file_handler)
    return log_path
