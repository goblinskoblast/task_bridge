"""
AI Provider Abstraction Layer
Unified interface for different AI providers (Anthropic, OpenClaw, OpenAI, etc.)
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any
import logging
import json
import re

logger = logging.getLogger(__name__)


def _extract_text_content(response: Any) -> str:
    if response is None:
        return ""

    if isinstance(response, str):
        return response

    blocks = getattr(response, "content", None)
    if isinstance(blocks, list):
        parts: List[str] = []
        for block in blocks:
            text = getattr(block, "text", None)
            if text:
                parts.append(text)
        if parts:
            return "\n".join(parts).strip()

    if isinstance(response, dict):
        content = response.get("content")
        if isinstance(content, str):
            return content

    return str(response)


def _parse_json_text(raw: str) -> Dict[str, Any]:
    text = (raw or "").strip()
    if not text:
        return {}

    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise


class AIProvider(ABC):
    @abstractmethod
    async def analyze_message(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 500,
        response_format: Optional[Dict] = None
    ) -> Dict[str, Any]:
        pass

    @abstractmethod
    async def analyze_email(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 500,
        response_format: Optional[Dict] = None
    ) -> Dict[str, Any]:
        pass

    @abstractmethod
    async def get_support_response(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 1000
    ) -> Dict[str, Any]:
        pass

    @abstractmethod
    async def analyze_image(
        self,
        image_base64: str,
        prompt: str,
        temperature: float = 0.3,
        max_tokens: int = 1000
    ) -> str:
        pass


class OpenClawProvider(AIProvider):
    def __init__(self, base_url: str, model: str, timeout: int = 30):
        from bot.openclaw_client import OpenClawClient
        from config import OPENCLAW_ENFORCE_SDD_SPEC, OPENCLAW_SDD_SPEC_PATH, OPENCLAW_SDD_MAX_CHARS

        self.client = OpenClawClient(
            base_url=base_url,
            model=model,
            timeout=timeout,
            enforce_spec=OPENCLAW_ENFORCE_SDD_SPEC,
            spec_path=OPENCLAW_SDD_SPEC_PATH,
            max_spec_chars=OPENCLAW_SDD_MAX_CHARS
        )
        logger.info(
            "OpenClawProvider initialized: %s, model=%s, spec_enforced=%s, spec_path=%s",
            base_url,
            model,
            OPENCLAW_ENFORCE_SDD_SPEC,
            OPENCLAW_SDD_SPEC_PATH,
        )

    async def analyze_message(self, messages, temperature=0.3, max_tokens=500, response_format=None):
        try:
            if response_format and response_format.get("type") == "json_object":
                result = await self.client.create_completion_with_json(
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens
                )
            else:
                response = await self.client.create_completion(
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    response_format=response_format
                )
                result = self._extract_content(response)
            logger.debug("OpenClaw analyze_message result: %s", result)
            return result
        except Exception as e:
            logger.error("OpenClaw analyze_message error: %s", e)
            raise

    async def analyze_email(self, messages, temperature=0.3, max_tokens=500, response_format=None):
        return await self.analyze_message(messages, temperature, max_tokens, response_format)

    async def get_support_response(self, messages, temperature=0.7, max_tokens=1000):
        try:
            result = await self.client.create_completion_with_json(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens
            )
            logger.debug("OpenClaw support response: %s", result)
            return result
        except Exception as e:
            logger.error("OpenClaw support response error: %s", e)
            raise

    async def analyze_image(self, image_base64, prompt, temperature=0.3, max_tokens=1000):
        try:
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}},
                    ],
                }
            ]
            response = await self.client.create_completion(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens
            )
            content = self._extract_content(response)
            if isinstance(content, dict):
                return content.get("content", str(content))
            return str(content)
        except Exception as e:
            logger.error("OpenClaw image analysis error: %s", e)
            raise

    def _extract_content(self, response: Any) -> Any:
        if isinstance(response, dict):
            if "choices" in response and len(response["choices"]) > 0:
                return response["choices"][0].get("message", {}).get("content", "")
            if "content" in response:
                return response["content"]
            if "output" in response:
                return response["output"]
        return response

    async def close(self):
        await self.client.close()


class OpenAIProvider(AIProvider):
    def __init__(self, api_key: str, model: str = "gpt-4o-mini"):
        from openai import AsyncOpenAI

        self.client = AsyncOpenAI(api_key=api_key)
        self.model = model
        logger.info("OpenAIProvider initialized: model=%s", model)

    async def analyze_message(self, messages, temperature=0.3, max_tokens=500, response_format=None):
        try:
            kwargs = {
                "model": self.model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            if response_format:
                kwargs["response_format"] = response_format
            response = await self.client.chat.completions.create(**kwargs)
            content = response.choices[0].message.content
            if response_format and response_format.get("type") == "json_object":
                return json.loads(content)
            return {"content": content}
        except Exception as e:
            logger.error("OpenAI analyze_message error: %s", e)
            raise

    async def analyze_email(self, messages, temperature=0.3, max_tokens=500, response_format=None):
        return await self.analyze_message(messages, temperature, max_tokens, response_format)

    async def get_support_response(self, messages, temperature=0.7, max_tokens=1000):
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
            )
            return json.loads(response.choices[0].message.content)
        except Exception as e:
            logger.error("OpenAI support response error: %s", e)
            raise

    async def analyze_image(self, image_base64, prompt, temperature=0.3, max_tokens=1000):
        try:
            response = await self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}},
                        ],
                    }
                ],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error("OpenAI image analysis error: %s", e)
            raise

    async def close(self):
        await self.client.close()


class AnthropicProvider(AIProvider):
    def __init__(self, api_key: str, model: str = "claude-3-7-sonnet-latest"):
        from anthropic import AsyncAnthropic

        self.client = AsyncAnthropic(api_key=api_key)
        self.model = model
        logger.info("AnthropicProvider initialized: model=%s", model)

    async def analyze_message(self, messages, temperature=0.3, max_tokens=500, response_format=None):
        try:
            system_parts: List[str] = []
            anthropic_messages: List[Dict[str, str]] = []
            for message in messages:
                role = message.get("role", "user")
                content = message.get("content", "")
                if role == "system":
                    system_parts.append(content)
                else:
                    anthropic_messages.append({"role": role, "content": content})

            system_prompt = "\n\n".join(part for part in system_parts if part).strip()
            if response_format and response_format.get("type") == "json_object":
                suffix = "Return valid JSON only. Do not wrap the answer in markdown fences."
                system_prompt = f"{system_prompt}\n\n{suffix}".strip()

            response = await self.client.messages.create(
                model=self.model,
                system=system_prompt or None,
                messages=anthropic_messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            text = _extract_text_content(response)
            if response_format and response_format.get("type") == "json_object":
                return _parse_json_text(text)
            return {"content": text}
        except Exception as e:
            logger.error("Anthropic analyze_message error: %s", e)
            raise

    async def analyze_email(self, messages, temperature=0.3, max_tokens=500, response_format=None):
        return await self.analyze_message(messages, temperature, max_tokens, response_format)

    async def get_support_response(self, messages, temperature=0.7, max_tokens=1000):
        return await self.analyze_message(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )

    async def analyze_image(self, image_base64, prompt, temperature=0.3, max_tokens=1000):
        try:
            response = await self.client.messages.create(
                model=self.model,
                temperature=temperature,
                max_tokens=max_tokens,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/jpeg",
                                    "data": image_base64,
                                },
                            },
                        ],
                    }
                ],
            )
            return _extract_text_content(response)
        except Exception as e:
            logger.error("Anthropic image analysis error: %s", e)
            raise

    async def close(self):
        await self.client.close()


_provider: Optional[AIProvider] = None


def get_ai_provider() -> AIProvider:
    global _provider

    if _provider is None:
        from config import (
            AI_PROVIDER,
            ANTHROPIC_API_KEY,
            ANTHROPIC_MODEL,
            OPENCLAW_BASE_URL,
            OPENCLAW_MODEL,
            OPENCLAW_TIMEOUT,
            OPENAI_API_KEY,
            OPENAI_MODEL,
        )

        if AI_PROVIDER == "openclaw":
            logger.info("Using OpenClaw AI provider")
            _provider = OpenClawProvider(
                base_url=OPENCLAW_BASE_URL,
                model=OPENCLAW_MODEL,
                timeout=OPENCLAW_TIMEOUT,
            )
        elif AI_PROVIDER == "openai":
            logger.info("Using OpenAI AI provider")
            _provider = OpenAIProvider(
                api_key=OPENAI_API_KEY,
                model=OPENAI_MODEL,
            )
        elif AI_PROVIDER == "anthropic":
            logger.info("Using Anthropic AI provider")
            _provider = AnthropicProvider(
                api_key=ANTHROPIC_API_KEY,
                model=ANTHROPIC_MODEL,
            )
        else:
            raise ValueError(f"Unknown AI_PROVIDER: {AI_PROVIDER}")

    return _provider


async def close_ai_provider():
    global _provider
    if _provider:
        await _provider.close()
        _provider = None
