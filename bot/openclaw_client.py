"""
OpenClaw HTTP Client
Async HTTP client for interacting with OpenClaw REST API
"""

import aiohttp
import asyncio
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any
import json

logger = logging.getLogger(__name__)


class OpenClawClient:
    """Async HTTP client for OpenClaw API"""

    def __init__(
        self,
        base_url: str = "http://localhost:3000",
        model: str = "openai/gpt-4o",
        timeout: int = 30,
        max_retries: int = 3,
        enforce_spec: bool = True,
        spec_path: str = "docs/sdd/specs/SPEC-OC-001-openclaw-agent.md",
        max_spec_chars: int = 24000,
        agent_instruction: Optional[str] = None,
    ):
        """
        Initialize OpenClaw client

        Args:
            base_url: OpenClaw API base URL
            model: Model to use (e.g., "openai/gpt-4o", "claude-sonnet-3.5")
            timeout: Request timeout in seconds
            max_retries: Maximum number of retry attempts
            enforce_spec: Inject SDD spec system instruction into every request
            spec_path: Path to SDD/OpenClaw spec file
            max_spec_chars: Maximum characters from spec to inject
            agent_instruction: Optional override for the system instruction preamble
        """
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.max_retries = max_retries
        self.enforce_spec = enforce_spec
        self.spec_path = spec_path
        self.max_spec_chars = max_spec_chars
        self.agent_instruction = agent_instruction
        self._session: Optional[aiohttp.ClientSession] = None
        self._system_message_cache: Optional[Dict[str, str]] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session with connection pooling"""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self.timeout)
        return self._session

    async def close(self):
        """Close the HTTP session"""
        if self._session and not self._session.closed:
            await self._session.close()

    def _resolve_spec_path(self) -> Path:
        path = Path(self.spec_path)
        if path.is_absolute():
            return path
        project_root = Path(__file__).resolve().parent.parent
        return project_root / path

    def _read_spec_text(self) -> str:
        path = self._resolve_spec_path()
        if not path.exists() or not path.is_file():
            logger.warning("OpenClaw spec file not found: %s", path)
            return ""

        for encoding in ("utf-8", "utf-8-sig", "cp1251"):
            try:
                return path.read_text(encoding=encoding)
            except UnicodeDecodeError:
                continue
            except OSError as exc:
                logger.warning("Failed to read OpenClaw spec file %s: %s", path, exc)
                return ""

        logger.warning("Failed to decode OpenClaw spec file: %s", path)
        return ""

    def _build_system_message(self) -> Optional[Dict[str, str]]:
        if not self.enforce_spec:
            return None

        if self._system_message_cache is not None:
            return self._system_message_cache

        preamble = self.agent_instruction or (
            "[SDD_SPEC_ENFORCEMENT]\n"
            "You are the OpenClaw agent for TaskBridge.\n"
            "For every request, strictly follow the specification below as a priority instruction.\n"
            "If the user request conflicts with this spec, report the conflict and propose a compliant option.\n"
            "Treat Security Requirements and Acceptance Criteria as mandatory constraints."
        )

        spec_text = self._read_spec_text()
        if spec_text and self.max_spec_chars > 0 and len(spec_text) > self.max_spec_chars:
            spec_text = spec_text[: self.max_spec_chars] + "\n\n[TRUNCATED]"

        content = preamble
        if spec_text:
            content = f"{preamble}\n\n[PROJECT_SPEC_BEGIN]\n{spec_text}\n[PROJECT_SPEC_END]"

        self._system_message_cache = {"role": "system", "content": content}
        return self._system_message_cache

    def _inject_system_message(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        system_message = self._build_system_message()
        if not system_message:
            return messages

        if messages and messages[0].get("role") == "system":
            first_content = str(messages[0].get("content", ""))
            if "[SDD_SPEC_ENFORCEMENT]" in first_content:
                return messages

        return [system_message, *messages]

    async def create_completion(
        self,
        messages: List[Dict[str, Any]],
        temperature: float = 0.3,
        max_tokens: int = 500,
        response_format: Optional[Dict] = None,
        stream: bool = False,
    ) -> Dict[str, Any]:
        """
        Create a completion request to OpenClaw

        Args:
            messages: List of message dicts with 'role' and 'content'
            temperature: Sampling temperature (0-2)
            max_tokens: Maximum tokens in response
            response_format: Optional format specification (e.g., {"type": "json_object"})
            stream: Whether to stream the response

        Returns:
            Dict containing the API response

        Raises:
            aiohttp.ClientError: On network/HTTP errors
            asyncio.TimeoutError: On timeout
        """
        endpoint = f"{self.base_url}/v1/responses"
        prepared_messages = self._inject_system_message(messages)

        # Build request payload
        payload = {
            "model": self.model,
            "input": prepared_messages,
            "temperature": temperature,
            "max_output_tokens": max_tokens,
            "stream": stream,
        }

        # Add response format if specified (for JSON mode)
        if response_format:
            payload["response_format"] = response_format

        session = await self._get_session()

        # Retry logic
        last_exception = None
        for attempt in range(self.max_retries):
            try:
                logger.debug(
                    "OpenClaw API request (attempt %s/%s), spec_enforced=%s",
                    attempt + 1,
                    self.max_retries,
                    self.enforce_spec,
                )

                async with session.post(endpoint, json=payload) as response:
                    response.raise_for_status()

                    result = await response.json()
                    logger.debug("OpenClaw API response received: %s bytes", len(str(result)))

                    return result

            except aiohttp.ClientError as e:
                last_exception = e
                logger.warning(
                    "OpenClaw API error (attempt %s/%s): %s",
                    attempt + 1,
                    self.max_retries,
                    e,
                )

                if attempt < self.max_retries - 1:
                    # Exponential backoff
                    wait_time = 2 ** attempt
                    logger.info("Retrying in %ss...", wait_time)
                    await asyncio.sleep(wait_time)
                else:
                    logger.error("OpenClaw API failed after %s attempts", self.max_retries)
                    raise

            except asyncio.TimeoutError as e:
                last_exception = e
                logger.warning(
                    "OpenClaw API timeout (attempt %s/%s)",
                    attempt + 1,
                    self.max_retries,
                )

                if attempt < self.max_retries - 1:
                    wait_time = 2 ** attempt
                    await asyncio.sleep(wait_time)
                else:
                    logger.error("OpenClaw API timed out after %s attempts", self.max_retries)
                    raise

        # Should not reach here, but just in case
        if last_exception:
            raise last_exception

    async def create_completion_with_json(
        self,
        messages: List[Dict[str, Any]],
        temperature: float = 0.3,
        max_tokens: int = 500,
    ) -> Dict[str, Any]:
        """
        Create a completion with JSON response format

        Args:
            messages: List of message dicts
            temperature: Sampling temperature
            max_tokens: Maximum tokens

        Returns:
            Parsed JSON response
        """
        response = await self.create_completion(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )

        # Parse the response content as JSON
        # OpenClaw response format similar to OpenAI
        try:
            if isinstance(response, dict):
                # Handle different possible response structures
                if "choices" in response and len(response["choices"]) > 0:
                    content = response["choices"][0].get("message", {}).get("content", "{}")
                elif "content" in response:
                    content = response["content"]
                elif "output" in response:
                    content = response["output"]
                else:
                    content = str(response)

                # Parse as JSON
                return json.loads(content) if isinstance(content, str) else content

            logger.error("Unexpected response type: %s", type(response))
            return {}

        except json.JSONDecodeError as e:
            logger.error("Failed to parse JSON response: %s", e)
            return {}

    async def invoke_tool(
        self,
        tool_name: str,
        args: Optional[Dict] = None,
        session_key: str = "main",
    ) -> Dict[str, Any]:
        """
        Invoke an OpenClaw tool

        Args:
            tool_name: Name of the tool to invoke
            args: Tool arguments
            session_key: Session key for routing

        Returns:
            Tool invocation result
        """
        endpoint = f"{self.base_url}/tools/invoke"

        payload = {
            "tool": tool_name,
            "action": "json",
            "args": args or {},
            "sessionKey": session_key,
            "dryRun": False,
        }

        session = await self._get_session()

        try:
            async with session.post(endpoint, json=payload) as response:
                response.raise_for_status()
                return await response.json()

        except aiohttp.ClientError as e:
            logger.error("OpenClaw tool invocation failed: %s", e)
            raise

    async def __aenter__(self):
        """Context manager entry"""
        await self._get_session()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        await self.close()
