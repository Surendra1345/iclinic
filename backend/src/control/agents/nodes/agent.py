"""The agent: one model that reads the patient, calls tools and writes the reply.

Each turn is a short loop. The model answers with tool calls or with its reply; every tool call is run by the
Toolbox (which enforces the safety rules) and its result goes back to the model, until the model replies in
plain text. If a model cannot be reached, or the loop never produces a reply, an error is raised: the turn is
rolled back and the patient gets one apology (see ConversationTurnService).
"""
import logging
import re
from typing import Any, Dict

from src.config.settings import settings
from src.control.agents.prompts import agent_system, build_context
from src.control.agents.toolbox import TOOL_SPECS, Toolbox
from src.core.services.llm_service import LLMError, llm_service

logger = logging.getLogger(__name__)

_LIST_MARKER = re.compile(r"^\s*(?:[-•]|\d+[.)])\s+", re.MULTILINE)


def clean_reply(text: str, channel: str) -> str:
    """Strip formatting a patient should never see or hear read out."""
    text = re.sub(r"[*`]+", "", text)
    text = re.sub(r"^\s*#+\s*", "", text, flags=re.MULTILINE).strip()
    if channel in ("outbound_call", "voice_assistant"):
        text = " ".join(_LIST_MARKER.sub("", text).split())
    return text


async def agent_node(state: Dict[str, Any], db) -> Dict[str, Any]:
    s = dict(state)
    channel = s.get("channel") or "chat"
    toolbox = Toolbox(db, s)
    system = agent_system(channel)
    messages = [{"role": "user", "text": build_context(s)}]

    reply = ""
    for _ in range(settings.LLM_AGENT_MAX_STEPS):
        turn = await llm_service.act(messages, system=system, tools=TOOL_SPECS, channel=channel)
        if not turn.calls:
            reply = turn.text
            break
        messages.append({"role": "model", "text": turn.text, "calls": turn.calls, "raw": turn.raw})
        results = []
        for call in turn.calls:
            result = await toolbox.call(call.name, call.args)
            logger.info("agent tool %s -> %s", call.name, result.get("status"))
            results.append({"name": call.name, "response": result})
        messages.append({"role": "tool", "results": results})
    if not reply:
        raise LLMError("the agent did not produce a reply within the step limit")

    choices = toolbox.finish_turn()
    out = {k: v for k, v in s.items() if k != "messages"}
    out.update({"latest_agent_speech": clean_reply(reply, channel), "choices": choices, "speech_localized": False})
    return out
