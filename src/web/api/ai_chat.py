"""AI assistant scoped to Klar Device Normalizer.

Hard guarantees:
- The model only answers questions about device inventory / security
  posture / sources / metrics for this app. Anything outside the scope
  (cooking, scripts, jokes, general knowledge, current events, etc.) is
  rejected with a fixed canned reply BEFORE we even call OpenAI.
- The system prompt repeats the scope so the model itself refuses if
  the keyword filter lets something marginal through.
- Per-user rate limit (in-memory) prevents abuse and runaway cost.
- Token caps on input and output keep cost bounded and replies tight.
- We only log *metadata* (user, on/off-topic flag, latency) — never
  message content, since users may paste sensitive device IDs.
"""
from __future__ import annotations

import json
import os
import re
import time
from collections import defaultdict, deque
from typing import Any

import structlog
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from openai import OpenAI
from pydantic import BaseModel, Field

from src.storage.repository import DeviceRepository
from src.web.dependencies import get_current_user, get_repo

router = APIRouter()
logger = structlog.get_logger(__name__)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("AI_ASSISTANT_MODEL", "gpt-4o-mini")
RATE_LIMIT_PER_HOUR = 30
MAX_INPUT_TOKENS = 800
MAX_OUTPUT_TOKENS = 600
MAX_HISTORY_MESSAGES = 10  # keep the conversation short

CANNED_REFUSAL = "Solo puedo ayudar con preguntas sobre Klar Device Normalizer."

# Single source of truth for what counts as "in scope". Lowercase, matched
# as substrings against the latest user message. ALL entries here must be
# domain-specific nouns / sources / statuses — no question-style words
# like "what" or "how many", since those would let "what's the weather"
# slip through.
_DOMAIN_KEYWORDS = {
    # Core nouns
    "device", "devices", "dispositivo", "dispositivos", "equipo", "equipos",
    "laptop", "macbook", "windows", "linux", "iphone", "android",
    "fleet", "parque", "inventory", "inventario",
    # Sources
    "klar", "crowdstrike", "falcon", "jumpcloud", "okta", "edr", "mdm", "idp",
    # Statuses
    "managed", "fully_managed", "no_edr", "no_mdm", "idp_only", "idponly",
    "stale", "server", "vm", "fully", "shadow",
    # Concepts the dashboard surfaces
    "owner", "compliance", "cobertura", "coverage",
    "policy", "policies", "mfa", "filevault", "bitlocker",
    "sync", "snapshot", "trend", "deploy", "deprovision",
    "region", "mexico", "americas", "europe", "row",
    "risk", "quick win", "insight", "report",
    "serial", "hostname",
}

# Phrases we explicitly refuse, even if domain keywords sneak in.
_OFF_TOPIC_RED_FLAGS = re.compile(
    r"(receta|cooking|recipe|joke|chiste|"
    r"write\s+(me\s+)?a\s+(python|javascript|bash|shell)\s+script|"
    r"escribime?\s+un\s+script|"
    r"hackear|exploit|"
    r"ignore\s+(previous|prior|all)\s+instructions|"
    r"system\s+prompt|"
    r"jailbreak|"
    r"act\s+as\s+(a\s+)?different)",
    re.IGNORECASE,
)

_RATE_LIMIT: dict[str, deque[float]] = defaultdict(deque)


def _is_in_scope(message: str) -> bool:
    """Cheap pre-filter: must contain at least one domain keyword AND
    not match any off-topic red flag."""
    if not message or not message.strip():
        return False
    if _OFF_TOPIC_RED_FLAGS.search(message):
        return False
    lowered = message.lower()
    return any(kw in lowered for kw in _DOMAIN_KEYWORDS)


def _check_rate_limit(user: str) -> bool:
    """Returns True if user can send another message; mutates the deque."""
    now = time.time()
    window = _RATE_LIMIT[user]
    while window and now - window[0] > 3600:
        window.popleft()
    if len(window) >= RATE_LIMIT_PER_HOUR:
        return False
    window.append(now)
    return True


def _build_system_prompt(summary: dict[str, Any], last_sync: dict[str, Any] | None) -> str:
    """The system prompt is doing two jobs: scope enforcement and grounding
    the model in the latest fleet state so it doesn't fabricate counts."""
    summary_json = json.dumps(summary or {}, default=str)[:2000]
    last_sync_json = json.dumps(last_sync or {}, default=str)[:600]
    return f"""You are an AI assistant embedded in Klar Device Normalizer, a security inventory tool that aggregates device data from CrowdStrike (EDR), JumpCloud (MDM), and Okta (IDP).

You can ONLY answer questions about:
- Device inventory and statuses (FULLY_MANAGED, MANAGED, NO_EDR, NO_MDM, IDP_ONLY, SERVER, STALE, UNKNOWN)
- Coverage gaps and what each status implies
- The 3 sources and what data they provide
- Quick wins / insights / recommendations the dashboard surfaces
- Compliance metrics, risk score, deduplication, sync status
- Region distribution (MEXICO / AMERICAS / EUROPE / ROW)

REFUSE any question outside this scope. If asked about cooking, scripts, programming, jokes, current events, general knowledge, or anything unrelated to the inventory — respond with EXACTLY this string and nothing else:
{CANNED_REFUSAL}

Do NOT generate code unless it is a kubectl, curl, or SQL command to query this app's APIs or its SQLite DB. NEVER write Python, JavaScript, or shell scripts that do anything else.

Use the LATEST FLEET CONTEXT below as authoritative when the user asks for numbers. Do not invent counts. If the answer requires data not in the context, say so and suggest where to look in the dashboard.

LATEST FLEET CONTEXT (most recent sync summary):
{summary_json}

LAST SYNC METADATA:
{last_sync_json}

Respond in the same language as the user (Spanish or English). Keep answers concise — under 200 words unless the user explicitly asks for a long explanation."""


class ChatMessage(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(min_length=1, max_length=4000)


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1)


def _truncated_history(messages: list[ChatMessage]) -> list[dict[str, str]]:
    return [{"role": m.role, "content": m.content[:2000]} for m in messages[-MAX_HISTORY_MESSAGES:]]


@router.post("/api/ai/chat")
async def api_ai_chat(
    body: ChatRequest,
    repo: DeviceRepository = Depends(get_repo),
    current_user: str | None = Depends(get_current_user),
) -> Any:
    """Chat endpoint scoped to Klar Device Normalizer.

    Errors map to specific status codes the frontend can branch on:
    - 401: not authenticated (handled by middleware in practice)
    - 429: per-user rate limit hit
    - 503: OpenAI not configured
    - 400: empty / malformed input
    """
    user = current_user or "anonymous"

    if not OPENAI_API_KEY:
        return JSONResponse(
            content={"error": "AI assistant is not configured (missing OPENAI_API_KEY)."},
            status_code=503,
        )

    if not body.messages or body.messages[-1].role != "user":
        return JSONResponse(
            content={"error": "Last message must come from the user."},
            status_code=400,
        )

    if not _check_rate_limit(user):
        logger.info("ai_chat_rate_limited", user=user)
        return JSONResponse(
            content={"error": f"Rate limit reached ({RATE_LIMIT_PER_HOUR}/hour). Try again later."},
            status_code=429,
        )

    last_user_msg = body.messages[-1].content.strip()

    # Pre-filter: cheap reject without burning OpenAI tokens.
    if not _is_in_scope(last_user_msg):
        logger.info("ai_chat_refused_offtopic", user=user, length=len(last_user_msg))
        return JSONResponse(content={
            "reply": CANNED_REFUSAL,
            "in_scope": False,
        })

    # Build context from the latest data the dashboard already exposes.
    try:
        summary = repo.get_summary()
        last_sync = repo.get_last_sync_run() or {}
    except Exception as exc:
        logger.warning("ai_chat_context_fetch_failed", error=str(exc))
        summary, last_sync = {}, {}

    system_prompt = _build_system_prompt(summary, last_sync)
    history = _truncated_history(body.messages)

    started = time.time()
    try:
        client = OpenAI(api_key=OPENAI_API_KEY)
        completion = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "system", "content": system_prompt}, *history],
            max_tokens=MAX_OUTPUT_TOKENS,
            temperature=0.2,
        )
        reply = (completion.choices[0].message.content or "").strip()
    except Exception as exc:
        logger.error("ai_chat_openai_error", error=str(exc), user=user)
        return JSONResponse(
            content={"error": "Could not reach the AI provider. Try again in a minute."},
            status_code=502,
        )

    elapsed_ms = int((time.time() - started) * 1000)
    logger.info(
        "ai_chat_ok",
        user=user,
        elapsed_ms=elapsed_ms,
        in_scope=True,
        reply_length=len(reply),
    )

    return JSONResponse(content={
        "reply": reply,
        "in_scope": True,
        "elapsed_ms": elapsed_ms,
    })
