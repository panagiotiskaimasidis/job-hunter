"""
Unified AI client with automatic Groq → Gemini failover.

Usage in any matcher module:
    from matcher.ai_client import generate

    text = generate(prompt, system=SYSTEM_CONTEXT, max_tokens=1024)

Strategy:
  1. Try Groq (llama-3.3-70b-versatile) — fast and free, 14,400 req/day.
  2. On any rate-limit / quota error, transparently switch to Gemini
     (gemini-2.0-flash) for the remainder of the process run.
  3. Exponential backoff is attempted once before switching providers.
"""

import logging
import re
import time
import threading

import config

logger = logging.getLogger(__name__)

# ── Provider state (process-global, thread-safe) ───────────────────────────
_lock = threading.Lock()
_groq_exhausted = False   # flipped True the first time Groq 429s without recovery

# ── Token usage tracking ───────────────────────────────────────────────────
_token_stats: dict = {
    "groq":   {"requests": 0, "prompt": 0, "completion": 0, "total": 0},
    "gemini": {"requests": 0, "prompt": 0, "completion": 0, "total": 0},
}
_stats_lock = threading.Lock()


def _record_groq_usage(usage) -> None:
    with _stats_lock:
        _token_stats["groq"]["requests"] += 1
        if usage:
            _token_stats["groq"]["prompt"]     += getattr(usage, "prompt_tokens", 0)
            _token_stats["groq"]["completion"] += getattr(usage, "completion_tokens", 0)
            _token_stats["groq"]["total"]      += getattr(usage, "total_tokens", 0)


def _record_gemini_usage(meta) -> None:
    with _stats_lock:
        _token_stats["gemini"]["requests"] += 1
        if meta:
            _token_stats["gemini"]["prompt"]     += getattr(meta, "prompt_token_count", 0)
            _token_stats["gemini"]["completion"] += getattr(meta, "candidates_token_count", 0)
            _token_stats["gemini"]["total"]      += getattr(meta, "total_token_count", 0)


def get_token_stats() -> dict:
    """Return a snapshot of accumulated token usage for this process run."""
    with _stats_lock:
        return {k: v.copy() for k, v in _token_stats.items()}


def groq_was_exhausted() -> bool:
    """Return True if Groq hit its rate limit and Gemini took over."""
    with _lock:
        return _groq_exhausted


def _mark_groq_exhausted():
    global _groq_exhausted
    with _lock:
        _groq_exhausted = True
    logger.warning("[ai_client] Groq exhausted — switching to Gemini for remainder of run")


def _groq_available() -> bool:
    with _lock:
        return not _groq_exhausted


# ── Groq call ──────────────────────────────────────────────────────────────

def _call_groq(prompt: str, system: str, max_tokens: int) -> str:
    from groq import Groq
    client = Groq(api_key=config.GROQ_API_KEY)

    for attempt in range(3):
        try:
            resp = client.chat.completions.create(
                model=config.GROQ_MODEL,
                max_tokens=max_tokens,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user",   "content": prompt},
                ],
            )
            _record_groq_usage(getattr(resp, "usage", None))
            return resp.choices[0].message.content

        except Exception as exc:
            msg = str(exc)
            is_rate = "rate_limit" in msg.lower() or "429" in msg or "tokens" in msg.lower()
            is_service = "503" in msg or "service" in msg.lower()

            is_connection = "connection" in msg.lower() or "timeout" in msg.lower()

            if (is_rate or is_service) and attempt < 2:
                # Parse exact wait from Groq's error message if present
                m = re.search(r'try again in (\d+)m([\d.]+)s', msg)
                if m:
                    wait = int(m.group(1)) * 60 + float(m.group(2)) + 5
                else:
                    wait = 2 ** attempt * 20  # 20s, 40s
                # If wait > 60s, don't wait — immediately fail over to Gemini
                if wait > 60:
                    logger.warning("[ai_client] Groq wants %ds wait — failing over to Gemini immediately", int(wait))
                    raise  # triggers failover in caller
                logger.warning("[ai_client] Groq rate limit — waiting %ds (attempt %d/3)", int(wait), attempt + 1)
                time.sleep(wait)
            elif is_connection and attempt < 2:
                # Brief retry on transient connection errors before failing over
                wait = 2 ** attempt * 5
                logger.warning("[ai_client] Groq connection error — retrying in %ds (attempt %d/3)", wait, attempt + 1)
                time.sleep(wait)
            else:
                # Give up on Groq — let caller decide whether to failover
                raise


# ── Gemini call ────────────────────────────────────────────────────────────

def _call_gemini(prompt: str, system: str, max_tokens: int) -> str:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=config.GEMINI_API_KEY)

    resp = client.models.generate_content(
        model=config.GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=max_tokens,
        ),
    )
    _record_gemini_usage(getattr(resp, "usage_metadata", None))
    return resp.text


# ── Public interface ───────────────────────────────────────────────────────

def generate(prompt: str, system: str = "", max_tokens: int = 1024) -> str:
    """
    Generate text via Groq first, falling back to Gemini on rate-limit errors.
    Raises on hard errors (bad key, no quota on either provider, etc.).
    """
    # If Groq is known-exhausted, go straight to Gemini
    if _groq_available():
        try:
            return _call_groq(prompt, system, max_tokens)
        except Exception as exc:
            msg = str(exc)
            is_quota = ("rate_limit" in msg.lower() or "429" in msg
                        or "tokens" in msg.lower() or "quota" in msg.lower()
                        or "connection" in msg.lower() or "timeout" in msg.lower())
            if is_quota and config.GEMINI_API_KEY:
                _mark_groq_exhausted()
                logger.info("[ai_client] Falling back to Gemini for this call")
                return _call_gemini(prompt, system, max_tokens)
            raise

    # Groq exhausted — use Gemini directly
    logger.debug("[ai_client] Using Gemini (Groq exhausted)")
    return _call_gemini(prompt, system, max_tokens)
