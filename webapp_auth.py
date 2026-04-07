from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Any
from urllib.parse import urlencode


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def build_webapp_auth_token(
    secret: str,
    user_id: int,
    *,
    created_ts: int | None = None,
    nonce: str | None = None,
) -> str:
    if not secret:
        raise ValueError("OAUTH_STATE_SECRET is not configured")

    normalized_user_id = int(user_id)
    if normalized_user_id <= 0:
        raise ValueError("Web session token user is invalid")

    payload = {
        "uid": normalized_user_id,
        "ts": int(created_ts or time.time()),
        "nonce": nonce or secrets.token_urlsafe(8),
    }
    payload_part = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = hmac.new(secret.encode("utf-8"), payload_part.encode("utf-8"), hashlib.sha256).digest()
    return f"{payload_part}.{_b64url_encode(signature)}"


def verify_webapp_auth_token(
    secret: str,
    token: str,
    *,
    ttl_seconds: int,
    now_ts: int | None = None,
) -> int:
    if not secret:
        raise ValueError("OAUTH_STATE_SECRET is not configured")

    try:
        payload_part, sign_part = token.split(".", 1)
    except ValueError as exc:
        raise ValueError("Invalid web session token") from exc

    expected_sign = hmac.new(secret.encode("utf-8"), payload_part.encode("utf-8"), hashlib.sha256).digest()
    provided_sign = _b64url_decode(sign_part)
    if not hmac.compare_digest(expected_sign, provided_sign):
        raise ValueError("Web session token signature is invalid")

    payload = json.loads(_b64url_decode(payload_part).decode("utf-8"))
    created_ts = int(payload.get("ts", 0))
    if created_ts <= 0:
        raise ValueError("Web session token timestamp is invalid")

    current_ts = int(now_ts or time.time())
    if current_ts - created_ts > int(ttl_seconds):
        raise ValueError("Web session token has expired")

    user_id = int(payload.get("uid", 0))
    if user_id <= 0:
        raise ValueError("Web session token user is invalid")
    return user_id


def resolve_authenticated_webapp_user(
    *,
    init_data: str | None,
    signed_token: str | None,
    verify_telegram_init_data: Any,
    verify_signed_token: Any,
) -> tuple[str, Any]:
    init_error: Exception | None = None

    if init_data:
        try:
            return "telegram", verify_telegram_init_data(init_data)
        except Exception as exc:  # pragma: no cover - behavior verified via return/raise contract
            init_error = exc

    if signed_token:
        return "signed", verify_signed_token(signed_token)

    if init_error:
        raise init_error

    raise ValueError("Authentication required")


def build_signed_webapp_url(
    base_domain: str,
    *,
    user_id: int,
    mode: str | None = None,
    task_id: int | None = None,
    tab: str | None = None,
    extra_params: dict[str, Any] | None = None,
    auth_secret: str | None = None,
) -> str:
    normalized_base = (base_domain or "").strip().rstrip("/")
    if not normalized_base:
        raise ValueError("WEB_APP_DOMAIN is not configured")

    query_params: dict[str, Any] = {"user_id": int(user_id)}
    if mode:
        query_params["mode"] = mode
    if task_id is not None:
        query_params["task_id"] = int(task_id)
    if tab:
        query_params["tab"] = tab
    for key, value in (extra_params or {}).items():
        if value is not None:
            query_params[str(key)] = value
    if auth_secret:
        query_params["tb_auth"] = build_webapp_auth_token(auth_secret, int(user_id))

    return f"{normalized_base}/webapp/index.html?{urlencode(query_params)}"
