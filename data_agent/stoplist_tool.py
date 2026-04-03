from __future__ import annotations

from .adapters import italian_pizza_public_adapter


class StoplistTool:
    async def collect_for_point(self, *, url: str, username: str, encrypted_password: str, point_name: str) -> dict:
        return await italian_pizza_public_adapter.collect_stoplist(point_name)


stoplist_tool = StoplistTool()
