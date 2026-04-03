from __future__ import annotations

from .adapters import italian_pizza_portal_adapter


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
        return await italian_pizza_portal_adapter.collect_blanks(
            url=url,
            username=username,
            encrypted_password=encrypted_password,
            point_name=point_name,
            period_hint=period_hint,
        )


blanks_tool = BlanksTool()
