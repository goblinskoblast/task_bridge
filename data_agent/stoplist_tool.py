from __future__ import annotations

from .browser_agent import browser_agent
from .italian_pizza import build_stoplist_task


class StoplistTool:
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
        return {
            "status": "ok",
            "point_name": point_name,
            "report_text": data,
        }


stoplist_tool = StoplistTool()
