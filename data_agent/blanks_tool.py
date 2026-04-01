from __future__ import annotations

import hashlib
import re

from .browser_agent import browser_agent
from .italian_pizza import build_blanks_task


class BlanksTool:
    def _normalize_report(self, point_name: str, data: str) -> tuple[str, bool]:
        raw = (data or "").strip()
        if not raw:
            return (
                f"Точка: {point_name}\nПроверка бланков не дала результата. Нужен повторный запуск.",
                False,
            )

        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        filtered: list[str] = []
        for line in lines:
            lowered = line.lower()
            if any(marker in lowered for marker in ["cookie", "войти", "login", "пароль", "скачать приложение"]):
                continue
            filtered.append(line)

        body = "\n".join(filtered[:50]).strip() or raw[:3500]
        has_red_flags = bool(re.search(r"красн|red|ошиб|отклон|лимит|закрыт", body, flags=re.IGNORECASE))
        status_line = "найдены красные бланки или отклонения" if has_red_flags else "красных бланков не найдено"
        return f"Точка: {point_name}\nСтатус: {status_line}\n{body}", has_red_flags

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
        report_text, has_red_flags = self._normalize_report(point_name, data)
        alert_hash = hashlib.sha256(report_text.encode("utf-8", errors="ignore")).hexdigest()
        return {
            "status": "ok",
            "point_name": point_name,
            "has_red_flags": has_red_flags,
            "alert_hash": alert_hash,
            "report_text": report_text,
        }


blanks_tool = BlanksTool()
