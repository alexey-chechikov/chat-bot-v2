from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, cast

import httpx

from .exceptions import (
    GinAreaAPIError,
    GinAreaAuthError,
    GinAreaRateLimitError,
    GinAreaServerError,
)

if TYPE_CHECKING:
    from .auth import GinAreaAuth


class GinAreaClient:
    def __init__(
        self,
        *,
        base_url: str = "https://ginarea.org/api",
        timeout: float = 30.0,
        rate_limit_min_interval: float = 1.1,
        max_retries_5xx: int = 3,
        auth: GinAreaAuth | None = None,
        token: str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.rate_limit_min_interval = rate_limit_min_interval
        self.max_retries_5xx = max_retries_5xx
        self.auth = auth
        self.token = token
        self._last_call_at = 0.0

    def request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        requires_auth: bool = True,
    ) -> dict[str, Any] | list[Any]:
        reauthed = False
        rate_retried = False
        server_attempts = 0

        while True:
            now = time.monotonic()
            elapsed = now - self._last_call_at
            if elapsed < self.rate_limit_min_interval:
                time.sleep(self.rate_limit_min_interval - elapsed)

            headers: dict[str, str] = {}
            if requires_auth:
                if not self.token:
                    if self.auth is None:
                        raise GinAreaAuthError("missing bearer token")
                    self.token = self.auth.login(self)
                headers["Authorization"] = f"Bearer {self.token}"

            url = f"{self.base_url}{path}"
            try:
                response = httpx.request(
                    method,
                    url,
                    json=json,
                    params=params,
                    timeout=self.timeout,
                    headers=headers,
                )
                self._last_call_at = time.monotonic()
            except httpx.TimeoutException as exc:
                raise GinAreaAPIError("timeout") from exc

            if response.status_code == 401 and requires_auth and self.auth is not None:
                if reauthed:
                    raise GinAreaAuthError("authentication failed after retry")
                self.token = self.auth.login(self)
                reauthed = True
                continue

            if response.status_code == 429:
                if rate_retried:
                    raise GinAreaRateLimitError("rate limit persisted after retry")
                time.sleep(121.0)
                rate_retried = True
                continue

            if 500 <= response.status_code < 600:
                if server_attempts >= self.max_retries_5xx:
                    raise GinAreaServerError(response.text)
                time.sleep(2**server_attempts)
                server_attempts += 1
                continue

            if 200 <= response.status_code < 300:
                # 2026-05-17: GinArea's /bots/{id}/start and /stop control
                # endpoints return 200 OK with EMPTY body. response.json() would
                # raise JSONDecodeError. Handle gracefully — empty body means
                # "operation accepted, no payload to return".
                body = response.text
                if not body or not body.strip():
                    return {}
                try:
                    return cast(dict[str, Any] | list[Any], response.json())
                except ValueError as e:
                    raise GinAreaAPIError(
                        f"{response.status_code}: non-JSON response body: "
                        f"{body[:200]!r} ({e})"
                    )

            if response.status_code == 401:
                raise GinAreaAuthError(response.text)
            raise GinAreaAPIError(f"{response.status_code}: {response.text}")
