from __future__ import annotations

from typing import Any

from config import OAUTH_STATE_SECRET, WEB_APP_DOMAIN
from webapp_auth import build_signed_webapp_url


def build_taskbridge_webapp_url(
    *,
    user_id: int,
    mode: str | None = None,
    task_id: int | None = None,
    tab: str | None = None,
    extra_params: dict[str, Any] | None = None,
) -> str:
    return build_signed_webapp_url(
        WEB_APP_DOMAIN,
        user_id=user_id,
        mode=mode,
        task_id=task_id,
        tab=tab,
        extra_params=extra_params,
        auth_secret=OAUTH_STATE_SECRET,
    )
