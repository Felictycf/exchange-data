from typing import Any

from .http_client import JsonHttpClient


class OmniClient:
    BASE_URL = "https://omni-client-api.prod.ap-northeast-1.variational.io"

    def __init__(self, timeout: float = 10.0):
        self.http = JsonHttpClient(self.BASE_URL, timeout=timeout)

    def get_stats(self) -> dict[str, Any]:
        data = self.http.get("/metadata/stats")
        if not isinstance(data, dict):
            raise ValueError("Unexpected Omni stats payload")
        return data
