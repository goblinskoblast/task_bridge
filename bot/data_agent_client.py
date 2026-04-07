from __future__ import annotations

import logging
from typing import Any, Dict, List

import aiohttp

from config import DATA_AGENT_TIMEOUT, DATA_AGENT_URL, INTERNAL_API_TOKEN

logger = logging.getLogger(__name__)


class DataAgentClient:
    def __init__(self, base_url: str | None = None, timeout_seconds: int | None = None) -> None:
        self.base_url = (base_url or DATA_AGENT_URL).rstrip("/")
        self.timeout_seconds = timeout_seconds or DATA_AGENT_TIMEOUT
        self.token = INTERNAL_API_TOKEN

    async def health(self) -> Dict[str, Any]:
        return await self._request("GET", "/health")

    async def chat(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return await self._request("POST", "/chat", json=payload)

    async def connect_system(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return await self._request("POST", "/systems/connect", json=payload)

    async def list_systems(self, user_id: int) -> List[Dict[str, Any]]:
        response = await self._request("GET", f"/systems/{user_id}")
        return response.get("systems", [])

    async def list_monitors(self, user_id: int) -> List[Dict[str, Any]]:
        response = await self._request("GET", f"/monitors/{user_id}")
        return response.get("monitors", [])

    async def delete_monitor(self, user_id: int, monitor_id: int) -> Dict[str, Any]:
        return await self._request("DELETE", f"/monitors/{user_id}/{monitor_id}")

    async def get_debug(self, user_id: int) -> Dict[str, Any]:
        return await self._request("GET", f"/debug/{user_id}")

    async def _request(self, method: str, path: str, json: Dict[str, Any] | None = None) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        timeout = aiohttp.ClientTimeout(total=self.timeout_seconds)
        headers = {}
        if self.token:
            headers["X-Internal-Token"] = self.token
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.request(method, url, json=json) as response:
                data = await response.json(content_type=None)
                if response.status >= 400:
                    raise RuntimeError(f"DataAgent request failed: {response.status} {data}")
                return data


data_agent_client = DataAgentClient()
