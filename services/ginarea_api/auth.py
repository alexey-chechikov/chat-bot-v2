from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import pyotp

from .exceptions import GinAreaAuthError

if TYPE_CHECKING:
    from .client import GinAreaClient


@dataclass(frozen=True)
class GinAreaCredentials:
    email: str
    password_sha1: str
    totp_secret: str


class GinAreaAuth:
    def __init__(self, creds: GinAreaCredentials) -> None:
        self.creds = creds

    @classmethod
    def from_env(cls) -> GinAreaAuth:
        email = os.environ["GINAREA_EMAIL"]
        pwd = os.environ["GINAREA_PASSWORD_SHA1"]
        totp = os.environ["GINAREA_TOTP_SECRET"]
        return cls(GinAreaCredentials(email, pwd, totp))

    def get_totp_code(self) -> str:
        return pyotp.TOTP(self.creds.totp_secret).now()

    def login(self, client: GinAreaClient) -> str:
        try:
            first = client.request(
                "POST",
                "/accounts/login",
                json={"email": self.creds.email, "password": self.creds.password_sha1},
                requires_auth=False,
            )
        except Exception as exc:
            raise GinAreaAuthError(str(exc)) from exc

        # Если 2FA не включён — финальный token уже в первом ответе
        if isinstance(first, dict) and not first.get("twoFactorEnable"):
            token = _extract_token(first)
            if token:
                client.token = token
                return token

        # 2FA: intermediate token из первого ответа → Bearer для /twoFactor
        intermediate = _extract_token(first)
        if not intermediate:
            raise GinAreaAuthError("login response missing accessToken")
        client.token = intermediate  # used as Bearer for next call

        try:
            second = client.request(
                "POST",
                "/accounts/twoFactor",
                json={"code": self.get_totp_code()},
                requires_auth=True,  # Bearer with intermediate token
            )
        except Exception as exc:
            raise GinAreaAuthError(str(exc)) from exc

        token = _extract_token(second)
        if not token:
            raise GinAreaAuthError("token missing from twoFactor response")
        client.token = token
        return token


def _extract_token(payload: dict[str, Any] | list[Any]) -> str | None:
    """Server uses 'accessToken'. Older docs/tests may use 'token'. Try both."""
    if not isinstance(payload, dict):
        return None
    token = payload.get("accessToken") or payload.get("token")
    return str(token) if token else None
