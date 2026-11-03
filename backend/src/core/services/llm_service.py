"""Model access for the conversation agent.

The agent is one model that talks to the patient and calls tools. Each call to `LLMService.act` is one
step of that loop: the model answers with text, with tool calls, or both. The provider behind it is
swappable (see `LLMProvider`); `GeminiProvider` is the default and brings retry, a backup-model list and a
temporary skip of failing models from `GeminiService`.

When every model fails, `LLMError` is raised; the turn is then rolled back and the patient gets one apology
(see ConversationTurnService).
"""
import asyncio
import json
import logging
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol

import httpx

from src.config.settings import settings
from src.handlers.http_clients.gemini_service import GeminiService
from src.observability.metrics import llm_call_duration_seconds, llm_calls_total

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """No model could produce a usable answer."""


@dataclass
class ToolCall:
    name: str
    args: Dict[str, Any] = field(default_factory=dict)
    id: str = ""      # set by providers that need to pair a tool result with its call


@dataclass
class ModelTurn:
    """One answer from the model: text for the patient, tool calls to run, or both."""
    text: str = ""
    calls: List[ToolCall] = field(default_factory=list)
    raw: Any = None   # the provider's own record of the answer, sent back unchanged on the next step


# Messages are provider-neutral dicts:
#   {"role": "user",  "text": "..."}
#   {"role": "model", "text": "...", "calls": [ToolCall, ...], "raw": <ModelTurn.raw>}
#   {"role": "tool",  "results": [{"name": "...", "response": {...}}, ...]}
Message = Dict[str, Any]


class LLMProvider(Protocol):
    async def generate_step(
        self, messages: List[Message], *, system: str, tools: List[Dict[str, Any]],
        temperature: float, max_tokens: int, timeout: float,
    ) -> ModelTurn: ...


class GeminiProvider:
    """Gemini through the shared GeminiService. `model` empty means GEMINI_MODEL."""

    def __init__(self, model: str = ""):
        self._service = GeminiService(model_name=model or None)

    @staticmethod
    def _contents(messages: List[Message]):
        from google.genai import types

        contents = []
        for message in messages:
            role = message["role"]
            if role == "user":
                contents.append(types.Content(role="user", parts=[types.Part(text=message["text"])]))
            elif role == "model":
                if isinstance(message.get("raw"), types.Content):
                    contents.append(message["raw"])
                else:
                    parts = [types.Part(text=message["text"])] if message.get("text") else []
                    # This answer came from another provider, so Gemini has no signature to send back for it.
                    parts += [types.Part(function_call=types.FunctionCall(name=c.name, args=c.args),
                                         thought_signature=b"skip_thought_signature_validator")
                              for c in message.get("calls", [])]
                    contents.append(types.Content(role="model", parts=parts))
            else:
                contents.append(types.Content(role="user", parts=[
                    types.Part.from_function_response(name=r["name"], response=r["response"])
                    for r in message["results"]
                ]))
        return contents

    async def generate_step(self, messages, *, system, tools, temperature, max_tokens, timeout) -> ModelTurn:
        from google.genai import types

        declarations = [
            types.FunctionDeclaration(name=t["name"], description=t["description"], parameters_json_schema=t["parameters"])
            for t in tools
        ]
        contents = self._contents(messages)
        response = await self._service._with_fallback(lambda model: self._service._call_model(
            model, contents, timeout,
            system_instruction=system, temperature=temperature, max_output_tokens=max_tokens,
            tools=[types.Tool(function_declarations=declarations)],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        ))
        candidates = getattr(response, "candidates", None) or []
        content = candidates[0].content if candidates else None
        parts = (content.parts if content is not None else None) or []
        text = "".join(p.text for p in parts if getattr(p, "text", None) and not getattr(p, "thought", False)).strip()
        calls = [ToolCall(p.function_call.name, dict(p.function_call.args or {})) for p in parts if getattr(p, "function_call", None)]
        return ModelTurn(text=text, calls=calls, raw=content)


class GroqProvider:
    """Groq's OpenAI-compatible chat API with tool calling.

    Tries each model in GROQ_MODELS in order; if all fail, the error is raised so the next provider is tried.
    """

    def __init__(self, models: str = "") -> None:
        self._models = [m.strip() for m in (models or settings.GROQ_MODELS).split(",") if m.strip()]

    @staticmethod
    def _messages(messages: List[Message], system: str) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = [{"role": "system", "content": system}]
        counter = 0
        last_ids: List[str] = []
        for message in messages:
            role = message["role"]
            if role == "user":
                out.append({"role": "user", "content": message["text"]})
            elif role == "model":
                last_ids = []
                tool_calls = []
                for call in message.get("calls", []):
                    counter += 1
                    call_id = call.id or f"call_{counter}"
                    last_ids.append(call_id)
                    tool_calls.append({"id": call_id, "type": "function",
                                       "function": {"name": call.name, "arguments": json.dumps(call.args)}})
                entry: Dict[str, Any] = {"role": "assistant", "content": message.get("text") or None}
                if tool_calls:
                    entry["tool_calls"] = tool_calls
                out.append(entry)
            else:
                for call_id, result in zip(last_ids, message["results"]):
                    out.append({"role": "tool", "tool_call_id": call_id, "content": json.dumps(result["response"], default=str)})
        return out

    async def _ask(self, model: str, messages, system, tools, temperature, max_tokens, timeout) -> ModelTurn:
        body: Dict[str, Any] = {
            "model": model, "messages": self._messages(messages, system),
            "temperature": temperature, "max_tokens": max_tokens,
            "tools": [{"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["parameters"]}} for t in tools],
            "tool_choice": "auto",
        }
        if model.startswith("openai/gpt-oss"):
            # These models spend part of max_tokens on hidden reasoning; keep it short so the reply is not cut off.
            body["reasoning_effort"] = "low"
        async with httpx.AsyncClient(timeout=timeout) as client:
            for attempt in range(2):
                response = await client.post(
                    f"{settings.GROQ_BASE_URL.rstrip('/')}/chat/completions", json=body,
                    headers={"Authorization": f"Bearer {settings.GROQ_API_KEY}"},
                )
                # Per-minute token limits reset in seconds: wait briefly once instead of giving up on the model.
                wait = response.headers.get("retry-after", "")
                if response.status_code == 429 and attempt == 0 and wait.replace(".", "", 1).isdigit() and float(wait) <= settings.GROQ_MAX_RETRY_WAIT_SECONDS:
                    await asyncio.sleep(float(wait) + 0.2)
                    continue
                break
        if response.status_code >= 400:
            logger.warning("Groq %s returned %s: %s", model, response.status_code, response.text[:300])
        response.raise_for_status()
        message = (response.json().get("choices") or [{}])[0].get("message") or {}
        calls = []
        for raw_call in message.get("tool_calls") or []:
            function = raw_call.get("function") or {}
            args = function.get("arguments") or "{}"
            calls.append(ToolCall(function["name"], json.loads(args) if isinstance(args, str) else dict(args), id=raw_call.get("id") or ""))
        # Some models (Qwen) write their reasoning inside <think> tags; the patient must never see it.
        text = re.sub(r"<think>.*?</think>", "", message.get("content") or "", flags=re.DOTALL).strip()
        return ModelTurn(text=text, calls=calls)

    async def generate_step(self, messages, *, system, tools, temperature, max_tokens, timeout) -> ModelTurn:
        last_error: Optional[BaseException] = None
        for model in self._models:
            try:
                turn = await self._ask(model, messages, system, tools, temperature, max_tokens, timeout)
                if turn.text or turn.calls:
                    return turn
                last_error = ValueError("empty answer")
            except Exception as exc:
                last_error = exc
                logger.warning("Groq model %s failed (%s)", model, type(exc).__name__)
        raise last_error or RuntimeError("no Groq model configured")


_PROVIDER_KEYS = {"groq": lambda: settings.GROQ_API_KEY, "gemini": lambda: settings.GEMINI_API_KEY}


class LLMService:
    """Runs one agent step on the first provider that works for the channel.

    Pass `provider` to use a single fixed provider for every channel (tests, scripts).
    """

    def __init__(self, provider: Optional[LLMProvider] = None) -> None:
        self._fixed = provider
        self._providers: Dict[str, LLMProvider] = {}
        self._down_until: Dict[str, float] = {}
        self._stats: Counter = Counter()

    # Providers are created on first use so the app starts (and tests import) without API keys.
    def _provider(self, name: str) -> LLMProvider:
        if name not in self._providers:
            self._providers[name] = GroqProvider() if name == "groq" else GeminiProvider(settings.LLM_AGENT_MODEL)
        return self._providers[name]

    @staticmethod
    def _order(channel: str) -> List[str]:
        raw = {"voice_assistant": settings.LLM_PROVIDERS_VOICE, "outbound_call": settings.LLM_PROVIDERS_CALL}.get(
            channel, settings.LLM_PROVIDERS_CHAT)
        return [n for n in (x.strip().lower() for x in raw.split(",")) if n in _PROVIDER_KEYS]

    def _candidates(self, channel: str) -> List[str]:
        """Providers for this channel, in order, that have a key; recently failed ones go last."""
        configured = [n for n in self._order(channel) if _PROVIDER_KEYS[n]()]
        now = time.monotonic()
        healthy = [n for n in configured if self._down_until.get(n, 0.0) <= now]
        return healthy + [n for n in configured if n not in healthy]

    def _record(self, outcome: str, started: float) -> None:
        self._stats[f"agent.{outcome}"] += 1
        llm_calls_total.labels("agent", outcome).inc()
        llm_call_duration_seconds.labels("agent").observe(time.perf_counter() - started)

    async def act(self, messages: List[Message], *, system: str, tools: List[Dict[str, Any]], channel: str = "chat") -> ModelTurn:
        """One step of the agent loop."""
        started = time.perf_counter()
        names = ["fixed"] if self._fixed is not None else self._candidates(channel)
        if not names:
            self._record("unavailable", started)
            raise LLMError("no model provider is configured for this channel")
        for name in names:
            provider = self._fixed if self._fixed is not None else self._provider(name)
            try:
                turn = await provider.generate_step(
                    messages, system=system, tools=tools,
                    temperature=settings.LLM_AGENT_TEMPERATURE, max_tokens=settings.LLM_AGENT_MAX_TOKENS,
                    timeout=settings.LLM_AGENT_TIMEOUT_SECONDS,
                )
                if not turn.text and not turn.calls:
                    raise ValueError("empty answer")
            except Exception as exc:
                self._stats[f"{name}.failed"] += 1
                self._down_until[name] = time.monotonic() + settings.LLM_PROVIDER_COOLDOWN_SECONDS
                logger.warning("agent model provider %s failed (%s)", name, type(exc).__name__)
                continue
            self._stats[f"{name}.ok"] += 1
            self._record("ok", started)
            return turn
        self._record("unavailable", started)
        raise LLMError("no model provider could answer")

    def get_stats(self) -> dict:
        return {
            "providers": {
                "chat": self._order("chat"), "call": self._order("outbound_call"), "voice": self._order("voice_assistant"),
            },
            "gemini_models": [m for m in [settings.LLM_AGENT_MODEL or settings.GEMINI_MODEL] + settings.GEMINI_FALLBACK_MODEL.split(",") if m.strip()],
            "groq_models": settings.GROQ_MODELS,
                        "max_steps_per_turn": settings.LLM_AGENT_MAX_STEPS,
            "calls": dict(self._stats),
        }


llm_service = LLMService()
