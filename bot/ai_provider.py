"""
AI Provider Abstraction Layer
Unified interface for different AI providers (OpenClaw, OpenAI, etc.)
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any
import logging
import json

logger = logging.getLogger(__name__)


class AIProvider(ABC):
    """Abstract base class for AI providers"""

    @abstractmethod
    async def analyze_message(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 500,
        response_format: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """
        Analyze a message and extract structured data

        Args:
            messages: List of message dicts with 'role' and 'content'
            temperature: Sampling temperature
            max_tokens: Maximum tokens in response
            response_format: Optional format specification

        Returns:
            Parsed response dict
        """
        pass

    @abstractmethod
    async def analyze_email(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 500,
        response_format: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """
        Analyze an email and extract structured data

        Args:
            messages: List of message dicts
            temperature: Sampling temperature
            max_tokens: Maximum tokens
            response_format: Optional format specification

        Returns:
            Parsed response dict
        """
        pass

    @abstractmethod
    async def get_support_response(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 1000
    ) -> Dict[str, Any]:
        """
        Get a support chatbot response

        Args:
            messages: Conversation history
            temperature: Sampling temperature
            max_tokens: Maximum tokens

        Returns:
            Support response dict
        """
        pass

    @abstractmethod
    async def analyze_image(
        self,
        image_base64: str,
        prompt: str,
        temperature: float = 0.3,
        max_tokens: int = 1000
    ) -> str:
        """
        Analyze an image using vision API

        Args:
            image_base64: Base64-encoded image
            prompt: Analysis prompt
            temperature: Sampling temperature
            max_tokens: Maximum tokens

        Returns:
            Analysis result text
        """
        pass


class OpenClawProvider(AIProvider):
    """OpenClaw AI provider implementation"""

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
            f"OpenClawProvider initialized: {base_url}, model={model}, "
            f"spec_enforced={OPENCLAW_ENFORCE_SDD_SPEC}, spec_path={OPENCLAW_SDD_SPEC_PATH}"
        )

    async def analyze_message(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 500,
        response_format: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """Analyze message using OpenClaw"""
        try:
            if response_format and response_format.get("type") == "json_object":
                # Use JSON mode
                result = await self.client.create_completion_with_json(
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens
                )
            else:
                # Regular completion
                response = await self.client.create_completion(
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    response_format=response_format
                )
                result = self._extract_content(response)

            logger.debug(f"OpenClaw analyze_message result: {result}")
            return result

        except Exception as e:
            logger.error(f"OpenClaw analyze_message error: {e}")
            raise

    async def analyze_email(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 500,
        response_format: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """Analyze email using OpenClaw (same as analyze_message)"""
        return await self.analyze_message(messages, temperature, max_tokens, response_format)

    async def get_support_response(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 1000
    ) -> Dict[str, Any]:
        """Get support response using OpenClaw"""
        try:
            # Support responses use JSON format
            result = await self.client.create_completion_with_json(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens
            )

            logger.debug(f"OpenClaw support response: {result}")
            return result

        except Exception as e:
            logger.error(f"OpenClaw support response error: {e}")
            raise

    async def analyze_image(
        self,
        image_base64: str,
        prompt: str,
        temperature: float = 0.3,
        max_tokens: int = 1000
    ) -> str:
        """Analyze image using OpenClaw vision API"""
        try:
            messages = [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": prompt
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{image_base64}"
                            }
                        }
                    ]
                }
            ]

            response = await self.client.create_completion(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens
            )

            content = self._extract_content(response)
            if isinstance(content, dict):
                return content.get('content', str(content))
            return str(content)

        except Exception as e:
            logger.error(f"OpenClaw image analysis error: {e}")
            raise

    def _extract_content(self, response: Any) -> Any:
        """Extract content from OpenClaw response"""
        if isinstance(response, dict):
            if 'choices' in response and len(response['choices']) > 0:
                return response['choices'][0].get('message', {}).get('content', '')
            elif 'content' in response:
                return response['content']
            elif 'output' in response:
                return response['output']
        return response

    async def close(self):
        """Close the client session"""
        await self.client.close()


class OpenAIProvider(AIProvider):
    """OpenAI AI provider implementation (fallback)"""

    def __init__(self, api_key: str, model: str = "gpt-4o-mini"):
        from openai import AsyncOpenAI

        self.client = AsyncOpenAI(api_key=api_key)
        self.model = model
        logger.info(f"OpenAIProvider initialized: model={model}")

    async def analyze_message(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 500,
        response_format: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """Analyze message using OpenAI"""
        try:
            kwargs = {
                "model": self.model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens
            }

            if response_format:
                kwargs["response_format"] = response_format

            response = await self.client.chat.completions.create(**kwargs)

            content = response.choices[0].message.content

            # Parse JSON if needed
            if response_format and response_format.get("type") == "json_object":
                return json.loads(content)

            return {"content": content}

        except Exception as e:
            logger.error(f"OpenAI analyze_message error: {e}")
            raise

    async def analyze_email(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 500,
        response_format: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """Analyze email using OpenAI (same as analyze_message)"""
        return await self.analyze_message(messages, temperature, max_tokens, response_format)

    async def get_support_response(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 1000
    ) -> Dict[str, Any]:
        """Get support response using OpenAI"""
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format={"type": "json_object"}
            )

            content = response.choices[0].message.content
            return json.loads(content)

        except Exception as e:
            logger.error(f"OpenAI support response error: {e}")
            raise

    async def analyze_image(
        self,
        image_base64: str,
        prompt: str,
        temperature: float = 0.3,
        max_tokens: int = 1000
    ) -> str:
        """Analyze image using OpenAI vision API"""
        try:
            response = await self.client.chat.completions.create(
                model="gpt-4o-mini",  # Vision model
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": prompt
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{image_base64}"
                                }
                            }
                        ]
                    }
                ],
                temperature=temperature,
                max_tokens=max_tokens
            )

            return response.choices[0].message.content

        except Exception as e:
            logger.error(f"OpenAI image analysis error: {e}")
            raise

    async def close(self):
        """Close the client (OpenAI client handles this automatically)"""
        await self.client.close()


# Global provider instance
_provider: Optional[AIProvider] = None


def get_ai_provider() -> AIProvider:
    """
    Get the configured AI provider instance (singleton pattern)

    Returns:
        Configured AIProvider instance
    """
    global _provider

    if _provider is None:
        from config import AI_PROVIDER, OPENCLAW_BASE_URL, OPENCLAW_MODEL, OPENCLAW_TIMEOUT, OPENAI_API_KEY, OPENAI_MODEL

        if AI_PROVIDER == "openclaw":
            logger.info("Using OpenClaw AI provider")
            _provider = OpenClawProvider(
                base_url=OPENCLAW_BASE_URL,
                model=OPENCLAW_MODEL,
                timeout=OPENCLAW_TIMEOUT
            )
        elif AI_PROVIDER == "openai":
            logger.info("Using OpenAI AI provider (fallback)")
            _provider = OpenAIProvider(
                api_key=OPENAI_API_KEY,
                model=OPENAI_MODEL
            )
        else:
            raise ValueError(f"Unknown AI_PROVIDER: {AI_PROVIDER}")

    return _provider


async def close_ai_provider():
    """Close the global AI provider instance"""
    global _provider
    if _provider:
        await _provider.close()
        _provider = None

