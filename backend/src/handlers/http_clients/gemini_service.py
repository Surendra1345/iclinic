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


_TRANSIENT_MARKERS = ("503", "504", "DEADLINE_EXCEEDED", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED", "500", "INTERNAL", "overloaded")


def _is_quota_exhausted(exc: BaseException) -> bool:
    return "RESOURCE_EXHAUSTED" in str(exc) or "429" in str(exc)


def _is_transient(exc: BaseException) -> bool:
    """Overload, rate-limit, server and timeout errors are worth retrying; 4xx config errors are not."""
    return isinstance(exc, asyncio.TimeoutError) or any(m in str(exc) for m in _TRANSIENT_MARKERS)


# model -> monotonic time until which it is skipped after a transient failure
_model_down_until: dict = {}
# models that rejected thinking_budget=0 (not every model supports turning thinking off)
_no_thinking_control: set = set()


class GeminiService:
    def __init__(self, api_key: Optional[str] = None, model_name: Optional[str] = None):
        self.api_key = api_key or settings.GEMINI_API_KEY
        self.model_name = model_name or settings.GEMINI_MODEL
        self.client = genai.Client(api_key=self.api_key or None)
        if not self.api_key:
            logger.warning("GEMINI_API_KEY not configured. Gemini calls will fail.")

    async def _call_model(self, model: str, contents: str, timeout: float, **config_kwargs):
        """One request to one model, with thinking disabled for speed where the model allows it."""
        use_thinking_off = settings.GEMINI_DISABLE_THINKING and model not in _no_thinking_control

        async def send(thinking_off: bool):
            kwargs = dict(config_kwargs)
            if thinking_off:
                kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
            return await asyncio.wait_for(
                self.client.aio.models.generate_content(
                    model=model, contents=contents, config=types.GenerateContentConfig(**kwargs)
                ),
                timeout=timeout,
            )

        try:
            return await send(use_thinking_off)
        except Exception as exc:
            if use_thinking_off and "INVALID_ARGUMENT" in str(exc):
                _no_thinking_control.add(model)
                return await send(False)
            raise

    async def _with_fallback(self, call):
        """Run call(model): retry the primary once on a fast transient error, then try the backup model."""
        models = [self.model_name]
        for backup in (m.strip() for m in settings.GEMINI_FALLBACK_MODEL.split(",")):
            if backup and backup not in models:
                models.append(backup)
        # Skip models that failed recently so a hung model costs one timeout, not one per request.
        now = time.monotonic()
        healthy = [m for m in models if _model_down_until.get(m, 0.0) <= now]
        if healthy:
            models = healthy
        last_exc: Optional[BaseException] = None
        for index, model in enumerate(models):
            attempts = 2 if index == 0 else 1
            for attempt in range(attempts):
                try:
                    return await call(model)
                except Exception as exc:
                    if not _is_transient(exc):
                        raise
                    last_exc = exc
                    if _is_quota_exhausted(exc):
                        # Retrying cannot help and the quota stays exhausted for a long time.
                        _model_down_until[model] = time.monotonic() + settings.GEMINI_QUOTA_CIRCUIT_SECONDS
                        break
                    # A timeout already used its time budget; retry only fast failures.
                    if attempt + 1 < attempts and not isinstance(exc, asyncio.TimeoutError):
                        await asyncio.sleep(settings.GEMINI_RETRY_DELAY_SECONDS)
                        continue
                    _model_down_until[model] = time.monotonic() + settings.GEMINI_CIRCUIT_SECONDS
                    break
            logger.warning("Gemini model %s unavailable (%s)", model, type(last_exc).__name__)
        assert last_exc is not None
        raise last_exc

    async def generate_content(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        temperature: float = 0.2,
        max_output_tokens: Optional[int] = None,
    ) -> str:
        """Generate plain text using the async SDK client."""
        started = time.perf_counter()
        try:
            response = await self._with_fallback(lambda model: self._call_model(
                model, prompt, settings.GEMINI_TIMEOUT_SECONDS,
                system_instruction=system_instruction,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
            ))
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
        return await self._with_fallback(lambda model: self._call_model(
            model, prompt, settings.GEMINI_STRUCTURED_TIMEOUT_SECONDS,
            system_instruction=system_instruction,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            response_mime_type="application/json",
            response_schema=response_schema,
        ))
