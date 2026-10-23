"""Shared async client for Google's maintained Gemini GenAI SDK."""
import asyncio
import logging
import time
from typing import Any, Optional, Type

from google import genai
from google.genai import types
from pydantic import BaseModel

from src.config.settings import settings
from src.observability.metrics import provider_request_duration_seconds

logger = logging.getLogger(__name__)


class GeminiService:
    def __init__(self, api_key: Optional[str] = None, model_name: Optional[str] = None):
        self.api_key = api_key or settings.GEMINI_API_KEY
        self.model_name = model_name or settings.GEMINI_MODEL
        self.client = genai.Client(api_key=self.api_key or None)
        if not self.api_key:
            logger.warning("GEMINI_API_KEY not configured. Gemini calls will fail.")

    async def generate_content(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        temperature: float = 0.2,
        max_output_tokens: Optional[int] = None,
    ) -> str:
        """Generate plain text using the async SDK client."""
        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
        )
        started = time.perf_counter()
        try:
            response = await asyncio.wait_for(
                self.client.aio.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                    config=config,
                ),
                timeout=15.0,
            )
            duration = time.perf_counter() - started
            provider_request_duration_seconds.labels("gemini", "generate_content").observe(duration)
            return response.text.strip() if response and response.text else ""
        except Exception as exc:
            provider_request_duration_seconds.labels("gemini", "generate_content").observe(
                time.perf_counter() - started
            )
            logger.error("Gemini generate_content failed (%s)", type(exc).__name__)
            raise

    async def generate_structured_content(
        self,
        prompt: str,
        *,
        response_schema: Type[BaseModel],
        system_instruction: Optional[str] = None,
        temperature: float = 0.0,
        max_output_tokens: int = 128,
    ) -> Any:
        """Generate JSON constrained by a Pydantic response schema."""
        return await self.client.aio.models.generate_content(
            model=self.model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
                response_mime_type="application/json",
                response_schema=response_schema,
            ),
        )
