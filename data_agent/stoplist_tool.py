from __future__ import annotations

import re

from .browser_agent import browser_agent
from .italian_pizza import build_stoplist_task


class StoplistTool:
    def _normalize_report(self, point_name: str, data: str) -> str:
        raw = (data or "").strip()
        if not raw:
            return (
                f"Стоп-лист для точки {point_name} не удалось собрать. "
                "Нужно повторить запуск и проверить доступность раздела стоп-листа."
            )

        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        filtered: list[str] = []
        for line in lines:
            lowered = line.lower()
            if any(marker in lowered for marker in ["cookie", "войти", "login", "пароль", "скачать приложение"]):
                continue
            filtered.append(line)

        body = "\n".join(filtered[:40]).strip() or raw[:3000]
        if re.search(r"нет\s+позици|стоп[- ]?лист\s+пуст|недоступных\s+позиций\s+нет", body, flags=re.IGNORECASE):
            return f"Точка: {point_name}\nСтатус: активных позиций в стоп-листе не найдено."

        return f"Точка: {point_name}\nСтоп-лист:\n{body}"

    async def collect_for_point(
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
            user_task=build_stoplist_task(point_name),
            progress_callback=None,
        )
        report_text = self._normalize_report(point_name, data)
        return {
            "status": "ok",
            "point_name": point_name,
            "report_text": report_text,
        }


stoplist_tool = StoplistTool()
