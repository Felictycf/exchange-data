from __future__ import annotations

from collections import defaultdict
from contextvars import ContextVar
from dataclasses import dataclass, field


run_id_var: ContextVar[str] = ContextVar("run_id", default="-")


@dataclass
class RetryStats:
    requests: int = 0
    retries: int = 0
    failures: int = 0
    recovered: int = 0
    retries_by_endpoint: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    failures_by_endpoint: dict[str, int] = field(default_factory=lambda: defaultdict(int))


stats_var: ContextVar[RetryStats] = ContextVar("retry_stats", default=RetryStats())


def set_run_id(run_id: str) -> None:
    run_id_var.set(run_id)
    stats_var.set(RetryStats())


def get_run_id() -> str:
    return run_id_var.get()


def mark_request() -> None:
    stats = stats_var.get()
    stats.requests += 1


def mark_retry(endpoint: str) -> None:
    stats = stats_var.get()
    stats.retries += 1
    stats.retries_by_endpoint[endpoint] += 1


def mark_failure(endpoint: str) -> None:
    stats = stats_var.get()
    stats.failures += 1
    stats.failures_by_endpoint[endpoint] += 1


def mark_recovered() -> None:
    stats = stats_var.get()
    stats.recovered += 1


def snapshot_stats() -> RetryStats:
    return stats_var.get()
