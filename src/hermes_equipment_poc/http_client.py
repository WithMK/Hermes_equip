from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


class AdapterError(RuntimeError):
    pass


@dataclass(frozen=True)
class JsonApiClient:
    base_url: str
    api_key: str = ""
    timeout_seconds: float = 20.0
    retry_count: int = 1
    max_response_bytes: int = 2_000_000
    api_key_header: str = "Authorization"
    api_key_prefix: str = "Bearer "

    def request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.base_url.rstrip('/')}/{path.lstrip('/')}"
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key:
            headers[self.api_key_header] = f"{self.api_key_prefix}{self.api_key}"
        request = urllib.request.Request(
            url,
            data=(json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None),
            headers=headers,
            method=method,
        )
        body = b""
        last_error: Exception | None = None
        for attempt in range(max(0, self.retry_count) + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                    body = response.read(self.max_response_bytes + 1)
                if len(body) > self.max_response_bytes:
                    raise AdapterError("Adapter response exceeded configured byte limit")
                break
            except urllib.error.HTTPError as exc:
                safe_body = exc.read(4096).decode("utf-8", errors="replace")
                if 500 <= exc.code < 600 and attempt < self.retry_count:
                    last_error = exc
                    time.sleep(0.2 * (attempt + 1))
                    continue
                raise AdapterError(f"Adapter returned HTTP {exc.code}: {safe_body}") from exc
            except (urllib.error.URLError, TimeoutError) as exc:
                last_error = exc
                if attempt < self.retry_count:
                    time.sleep(0.2 * (attempt + 1))
                    continue
                raise AdapterError(f"Adapter request failed: {type(exc).__name__}") from exc
        else:  # pragma: no cover - loop always exits or raises
            raise AdapterError(f"Adapter request failed: {type(last_error).__name__}") from last_error
        try:
            result = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AdapterError("Adapter returned invalid JSON") from exc
        if not isinstance(result, dict):
            raise AdapterError("Adapter response must be a JSON object")
        return result

    def get(self, path: str) -> dict[str, Any]:
        return self.request("GET", path)

    def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.request("POST", path, payload)
