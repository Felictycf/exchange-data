import json
import logging
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from exchange_monitor.run_state import mark_failure, mark_recovered, mark_request, mark_retry

logger = logging.getLogger(__name__)


class HttpClientError(RuntimeError):
    """Raised when an HTTP request fails."""


class JsonHttpClient:
    def __init__(self, base_url: str, timeout: float = 10.0, max_retries: int = 3):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.default_headers = {
            "Accept": "application/json",
            "User-Agent": "exchange-monitor/0.1 (+public-data-collector)",
        }

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        qs = f"?{urlencode(params)}" if params else ""
        url = f"{self.base_url}{path}{qs}"
        req = Request(url=url, method="GET", headers=self.default_headers)
        mark_request()

        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                with urlopen(req, timeout=self.timeout) as resp:
                    body = resp.read().decode("utf-8")
                    if attempt > 1:
                        mark_recovered()
                    return json.loads(body)
            except (HTTPError, URLError, json.JSONDecodeError) as exc:
                last_exc = exc
                if attempt < self.max_retries:
                    mark_retry(path)
                    wait_sec = 0.3 * attempt
                    logger.warning(
                        "request failed, retrying path=%s attempt=%d/%d wait=%.1fs error=%s",
                        path,
                        attempt,
                        self.max_retries,
                        wait_sec,
                        exc,
                    )
                    time.sleep(wait_sec)
                    continue
                mark_failure(path)
                break

        raise HttpClientError(f"GET {url} failed after {self.max_retries} attempts: {last_exc}") from last_exc
