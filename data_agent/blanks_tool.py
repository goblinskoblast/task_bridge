from __future__ import annotations

import logging
from typing import Any

from .adapters import italian_pizza_portal_adapter

logger = logging.getLogger(__name__)

_TRANSIENT_RETRY_STAGES = {"login_submit", "period_selection"}
_TRANSIENT_RETRY_STATUSES = {"failed", "needs_period"}


class BlanksTool:
    async def inspect_point(
        self,
        *,
        url: str,
        username: str,
        encrypted_password: str,
        point_name: str,
        period_hint: str = "",
    ) -> dict:
        first_result = await italian_pizza_portal_adapter.collect_blanks(
            url=url,
            username=username,
            encrypted_password=encrypted_password,
            point_name=point_name,
            period_hint=period_hint,
        )
        if not self._should_retry_transient_result(first_result):
            return first_result

        logger.info(
            "Retrying transient blanks failure point=%s stage=%s status=%s",
            point_name,
            self._diagnostics_stage(first_result),
            first_result.get("status"),
        )
        second_result = await italian_pizza_portal_adapter.collect_blanks(
            url=url,
            username=username,
            encrypted_password=encrypted_password,
            point_name=point_name,
            period_hint=period_hint,
        )
        if str(second_result.get("status") or "").lower() in {"ok", "completed"}:
            diagnostics = dict(second_result.get("diagnostics") or {})
            diagnostics["transient_retry_recovered"] = True
            second_result["diagnostics"] = diagnostics
            return second_result

        diagnostics = dict(second_result.get("diagnostics") or {})
        diagnostics["transient_retry_attempted"] = True
        second_result["diagnostics"] = diagnostics
        return second_result

    @staticmethod
    def _diagnostics_stage(result: dict[str, Any]) -> str:
        diagnostics = result.get("diagnostics") if isinstance(result, dict) else {}
        if not isinstance(diagnostics, dict):
            return ""
        return str(diagnostics.get("stage") or "").strip().lower()

    def _should_retry_transient_result(self, result: dict[str, Any]) -> bool:
        status = str(result.get("status") or "").strip().lower()
        if status not in _TRANSIENT_RETRY_STATUSES:
            return False
        return self._diagnostics_stage(result) in _TRANSIENT_RETRY_STAGES


blanks_tool = BlanksTool()
