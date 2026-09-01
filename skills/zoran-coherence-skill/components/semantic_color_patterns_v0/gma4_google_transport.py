from __future__ import annotations

import json
import os
from hashlib import sha256
import time
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from components.semantic_color_patterns_v0.gma4_teacher_adapter import GMA4_MODEL_ID

_GOOGLE_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class GMA4TransportError(RuntimeError):
    pass


def call_gma4_teacher(
    prompt: str,
    *,
    api_key: str | None = None,
    timeout_seconds: float = 20.0,
    opener: Callable[..., object] = urlopen,
    max_attempts: int = 3,
    backoff_seconds: float = 1.0,
    sleeper: Callable[[float], None] = time.sleep,
) -> str:
    """Call the same managed Gemma model already used by Zoran UI.

    Secret ownership remains server-side. The function returns raw model text;
    authority is granted only after strict deterministic contract parsing.
    """
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 30_000:
        raise ValueError("invalid prompt")
    key = (api_key if api_key is not None else os.environ.get("ZORAN_GEMMA_API_KEY", "")).strip()
    if len(key) < 12 or len(key) > 512:
        raise GMA4TransportError("GMA4_UNAVAILABLE: invalid or missing ZORAN_GEMMA_API_KEY")
    if timeout_seconds <= 0 or timeout_seconds > 120:
        raise ValueError("invalid timeout")
    if not isinstance(max_attempts, int) or isinstance(max_attempts, bool) or not 1 <= max_attempts <= 5:
        raise ValueError("invalid max_attempts")
    if backoff_seconds < 0 or backoff_seconds > 10:
        raise ValueError("invalid backoff")

    endpoint = _GOOGLE_ENDPOINT.format(model=GMA4_MODEL_ID)
    body = json.dumps({
        "systemInstruction": {
            "parts": [{"text": "Return exactly one top-level JSON object. Never return an array, a quoted JSON string, markdown, or prose."}],
        },
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.0,
            "maxOutputTokens": 1024,
            "responseMimeType": "application/json",
            "thinkingConfig": {"thinkingLevel": "minimal"},
        },
    }, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    request = Request(
        endpoint,
        data=body,
        headers={"Content-Type": "application/json", "x-goog-api-key": key},
        method="POST",
    )

    raw_bytes = b""
    jitter = (int(sha256(prompt.encode("utf-8")).hexdigest()[:4], 16) % 1000) / 1000
    for attempt in range(max_attempts):
        try:
            response = opener(request, timeout=timeout_seconds)
            raw_bytes = response.read()
            break
        except HTTPError as exc:
            retryable = exc.code in {429, 500, 502, 503, 504}
            if retryable and attempt + 1 < max_attempts:
                retry_after = None
                if exc.headers is not None:
                    try:
                        retry_after = float(exc.headers.get("Retry-After", ""))
                    except (TypeError, ValueError):
                        retry_after = None
                delay = min(
                    8.0,
                    retry_after if retry_after is not None else backoff_seconds * (2 ** attempt) + jitter,
                )
                sleeper(max(0.0, delay))
                continue
            raise GMA4TransportError(f"GMA4_HTTP_{exc.code}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            if attempt + 1 < max_attempts:
                sleeper(min(8.0, backoff_seconds * (2 ** attempt) + jitter))
                continue
            raise GMA4TransportError("GMA4_TRANSPORT_FAILURE") from exc

    try:
        payload = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GMA4TransportError("GMA4_INVALID_PROVIDER_JSON") from exc

    candidates = payload.get("candidates") if isinstance(payload, dict) else None
    if not isinstance(candidates, list) or not candidates:
        raise GMA4TransportError("GMA4_EMPTY_RESPONSE")
    content = candidates[0].get("content") if isinstance(candidates[0], dict) else None
    parts = content.get("parts") if isinstance(content, dict) else None
    if not isinstance(parts, list):
        raise GMA4TransportError("GMA4_EMPTY_RESPONSE")
    # Gemma 4 can emit provider-internal reasoning parts. They are evidence
    # neither for Zoran nor for the closed teacher contract and must never be
    # concatenated with the final JSON proposal.
    text = "".join(
        part.get("text", "")
        for part in parts
        if isinstance(part, dict) and part.get("thought") is not True
    ).strip()
    if not text:
        raise GMA4TransportError("GMA4_EMPTY_RESPONSE")
    return text
