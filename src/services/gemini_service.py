"""Gemini service — client wrapper for Google Gemini 2.0 Flash LLM."""
import logging
import time
from typing import Any, Optional
import google.generativeai as genai

from src.config.settings import settings
from src.observability.metrics import provider_request_duration_seconds

logger = logging.getLogger(__name__)


class GeminiService:

    def __init__(self, api_key: Optional[str] = None, model_name: Optional[str] = None):
        self.api_key = api_key or settings.GEMINI_API_KEY
        self.model_name = model_name or settings.GEMINI_MODEL
        if self.api_key:
            genai.configure(api_key=self.api_key)
        else:
            logger.warning("GEMINI_API_KEY not configured. Gemini calls will fail.")

    def get_model(self, system_instruction: Optional[str] = None, tools: Optional[list] = None) -> genai.GenerativeModel:
        """Instantiate configured GenerativeModel instance."""
        return genai.GenerativeModel(
            model_name=self.model_name,
            system_instruction=system_instruction,
            tools=tools,
        )

    async def generate_content(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        temperature: float = 0.2,
    ) -> str:
        """Direct text generation."""
        model = self.get_model(system_instruction=system_instruction)
        generation_config = genai.types.GenerationConfig(
            temperature=temperature,
        )
        try:
            started = time.perf_counter()
            response = await model.generate_content_async(
                prompt,
                generation_config=generation_config,
            )
            provider_request_duration_seconds.labels("gemini", "generate_content").observe(
                time.perf_counter() - started
            )
            return response.text.strip() if response.text else ""
        except Exception as e:
            provider_request_duration_seconds.labels("gemini", "generate_content").observe(
                time.perf_counter() - started
            )
            logger.error(f"Gemini generate_content failed: {e}")
            raise
