from __future__ import annotations

from typing import Any, Dict

import aiohttp

from config import DATA_AGENT_TIMEOUT, INTERNAL_API_TOKEN, INTERNAL_API_URL


class InternalApiClient:
    def __init__(self, base_url: str | None = None, token: str | None = None) -> None:
        self.base_url = (base_url or INTERNAL_API_URL).rstrip("/")
        self.token = token if token is not None else INTERNAL_API_TOKEN
        self.timeout_seconds = DATA_AGENT_TIMEOUT

    async def get_email_summary(self, user_id: int, days: int = 7) -> Dict[str, Any]:
        return await self._request("GET", f"/email/summary?user_id={user_id}&days={days}")

    async def get_calendar_events(self, user_id: int, days: int = 7) -> Dict[str, Any]:
        return await self._request("GET", f"/calendar/events?user_id={user_id}&days={days}")

    async def _request(self, method: str, path: str) -> Dict[str, Any]:
        headers = {}
        if self.token:
            headers["X-Internal-Token"] = self.token

        timeout = aiohttp.ClientTimeout(total=self.timeout_seconds)
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.request(method, f"{self.base_url}{path}") as response:
                data = await response.json(content_type=None)
                if response.status >= 400:
                    raise RuntimeError(f"Internal API request failed: {response.status} {data}")
                return data


internal_api_client = InternalApiClient()

