from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, List

import aiohttp

from config import DATA_AGENT_CHAT_TIMEOUT, DATA_AGENT_TIMEOUT, DATA_AGENT_URL, INTERNAL_API_TOKEN

logger = logging.getLogger(__name__)


class DataAgentClientError(RuntimeError):
    def __init__(self, message: str, *, user_message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.user_message = user_message
        self.status_code = status_code


class DataAgentTimeoutError(DataAgentClientError):
    pass


class DataAgentTransportError(DataAgentClientError):
    pass


class DataAgentResponseError(DataAgentClientError):
    pass


class DataAgentClient:
    def __init__(
        self,
        base_url: str | None = None,
        timeout_seconds: int | None = None,
        chat_timeout_seconds: int | None = None,
    ) -> None:
        self.base_url = (base_url or DATA_AGENT_URL).rstrip("/")
        self.timeout_seconds = timeout_seconds or DATA_AGENT_TIMEOUT
        self.chat_timeout_seconds = chat_timeout_seconds or DATA_AGENT_CHAT_TIMEOUT
        self.token = INTERNAL_API_TOKEN

    async def health(self) -> Dict[str, Any]:
        return await self._request("GET", "/health")

    async def chat(
        self,
        payload: Dict[str, Any],
        *,
        timeout_seconds: int | None = None,
        retry_attempts: int = 2,
    ) -> Dict[str, Any]:
        return await self._request(
            "POST",
            "/chat",
            json=payload,
            timeout_seconds=timeout_seconds or self.chat_timeout_seconds,
            retry_attempts=retry_attempts,
        )

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

    async def _request(
        self,
        method: str,
        path: str,
        json: Dict[str, Any] | None = None,
        *,
        timeout_seconds: int | None = None,
        retry_attempts: int = 1,
    ) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        effective_timeout = timeout_seconds or self.timeout_seconds
        attempts = max(retry_attempts, 1)

        for attempt in range(1, attempts + 1):
            timeout = aiohttp.ClientTimeout(total=effective_timeout)
            headers = {}
            if self.token:
                headers["X-Internal-Token"] = self.token

            try:
                async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
                    async with session.request(method, url, json=json) as response:
                        raw_text = await response.text()
                        data = self._decode_payload(raw_text, response.status, url)
                        if response.status >= 400:
                            error = self._build_http_error(response.status, data, raw_text, url)
                            if attempt < attempts and self._is_retryable_status(response.status):
                                logger.warning(
                                    "Retrying data-agent request after HTTP %s (%s/%s): %s",
                                    response.status,
                                    attempt,
                                    attempts,
                                    url,
                                )
                                await asyncio.sleep(0.75 * attempt)
                                continue
                            raise error
                        return data
            except DataAgentResponseError as exc:
                if attempt < attempts and self._is_retryable_status(exc.status_code):
                    logger.warning(
                        "Retrying data-agent request after response error (%s/%s): %s",
                        attempt,
                        attempts,
                        exc,
                    )
                    await asyncio.sleep(0.75 * attempt)
                    continue
                raise
            except asyncio.TimeoutError as exc:
                if attempt < attempts:
                    logger.warning(
                        "Retrying data-agent request after timeout (%s/%s): %s",
                        attempt,
                        attempts,
                        url,
                    )
                    await asyncio.sleep(0.75 * attempt)
                    continue
                raise DataAgentTimeoutError(
                    f"DataAgent request timed out after {effective_timeout}s: {url}",
                    user_message="Агент не успел ответить. Запрос выполняется слишком долго, попробуйте повторить чуть позже.",
                ) from exc
            except aiohttp.ClientError as exc:
                if attempt < attempts:
                    logger.warning(
                        "Retrying data-agent request after transport error (%s/%s): %s",
                        attempt,
                        attempts,
                        url,
                    )
                    await asyncio.sleep(0.75 * attempt)
                    continue
                raise DataAgentTransportError(
                    f"DataAgent transport error for {url}: {exc}",
                    user_message="Не удалось связаться с сервисом агента. Попробуйте ещё раз через минуту.",
                ) from exc

        raise DataAgentTransportError(
            f"DataAgent request retries exhausted for {url}",
            user_message="Не удалось связаться с сервисом агента. Попробуйте ещё раз через минуту.",
        )

    @staticmethod
    def _decode_payload(raw_text: str, status_code: int, url: str) -> Dict[str, Any]:
        normalized = (raw_text or "").strip()
        if not normalized:
            return {}

        try:
            payload = json.loads(normalized)
        except json.JSONDecodeError as exc:
            raise DataAgentResponseError(
                f"DataAgent returned non-JSON response status={status_code} url={url} body={DataAgentClient._summarize_body(normalized)}",
                user_message="Сервис агента вернул некорректный ответ. Попробуйте ещё раз через минуту.",
                status_code=status_code,
            ) from exc

        if isinstance(payload, dict):
            return payload
        return {"data": payload}

    @staticmethod
    def _build_http_error(status_code: int, data: Dict[str, Any], raw_text: str, url: str) -> DataAgentResponseError:
        if status_code == 403:
            user_message = "Внутренний доступ к агенту не прошёл. Проверьте связку сервисов на Railway."
        elif status_code in {502, 503, 504}:
            user_message = "Сервис агента временно недоступен. Попробуйте ещё раз через минуту."
        else:
            user_message = "Агент ответил ошибкой. Попробуйте повторить запрос чуть позже."

        detail = ""
        if isinstance(data, dict):
            detail = str(data.get("detail") or data.get("message") or "").strip()
        if not detail:
            detail = DataAgentClient._summarize_body(raw_text)

        return DataAgentResponseError(
            f"DataAgent request failed: status={status_code} url={url} detail={detail}",
            user_message=user_message,
            status_code=status_code,
        )

    @staticmethod
    def _is_retryable_status(status_code: int | None) -> bool:
        return status_code in {502, 503, 504}

    @staticmethod
    def _summarize_body(raw_text: str, limit: int = 240) -> str:
        compact = " ".join((raw_text or "").split())
        if len(compact) <= limit:
            return compact
        return compact[: limit - 3].rstrip() + "..."


data_agent_client = DataAgentClient()
