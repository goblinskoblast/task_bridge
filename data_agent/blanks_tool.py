from __future__ import annotations

import hashlib

from .browser_agent import browser_agent
from .italian_pizza import build_blanks_task


class BlanksTool:
    async def inspect_point(
        self,
        *,
        url: str,
        username: str,
        encrypted_password: str,
        point_name: str,
    ) -> dict:
        data = await browser_agent.extract_data(
            url=url,
            username=username,
            encrypted_password=encrypted_password,
            user_task=build_blanks_task(point_name),
            progress_callback=None,
        )
        lowered = (data or "").lower()
        has_red_flags = any(marker in lowered for marker in ["красн", "red", "ошиб", "отклон", "лимит", "закрыт"])
        alert_hash = hashlib.sha256((data or "").encode("utf-8", errors="ignore")).hexdigest()
        return {
            "status": "ok",
            "point_name": point_name,
            "has_red_flags": has_red_flags,
            "alert_hash": alert_hash,
            "report_text": data,
        }


blanks_tool = BlanksTool()
