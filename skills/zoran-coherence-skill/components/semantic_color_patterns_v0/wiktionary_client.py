from __future__ import annotations

import json
from hashlib import sha256
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, quote
from urllib.request import Request, urlopen

from components.semantic_color_patterns_v0.wiktionary_parser import (
    WiktionaryEntry,
    parse_french_wiktionary_html,
)

_API = "https://fr.wiktionary.org/w/api.php"


class WiktionaryClientError(RuntimeError):
    pass


def fetch_french_wiktionary_entry(
    surface: str,
    *,
    timeout_seconds: float = 12.0,
    opener=urlopen,
    max_attempts: int = 5,
    backoff_seconds: float = 2.0,
    max_backoff_seconds: float = 60.0,
    sleeper=time.sleep,
) -> WiktionaryEntry:
    if not surface.strip() or len(surface) > 200:
        raise ValueError("invalid surface")
    if timeout_seconds <= 0 or timeout_seconds > 60:
        raise ValueError("invalid timeout")
    if not isinstance(max_attempts, int) or isinstance(max_attempts, bool) or not 1 <= max_attempts <= 5:
        raise ValueError("invalid max_attempts")
    if backoff_seconds < 0 or backoff_seconds > 10:
        raise ValueError("invalid backoff")
    if max_backoff_seconds < 1 or max_backoff_seconds > 120:
        raise ValueError("invalid max_backoff")
    query = urlencode({
        "action": "parse",
        "page": surface,
        "prop": "text|revid",
        "redirects": "1",
        "format": "json",
        "formatversion": "2",
    })
    request = Request(
        f"{_API}?{query}",
        headers={"User-Agent": "ZoranSemanticLearning/0.1 (experimental)"},
        method="GET",
    )
    raw = b""
    jitter = (int(sha256(surface.casefold().encode("utf-8")).hexdigest()[:4], 16) % 500) / 1000
    for attempt in range(max_attempts):
        try:
            response = opener(request, timeout=timeout_seconds)
            raw = response.read()
            break
        except HTTPError as exc:
            if exc.code == 404:
                raise WiktionaryClientError("WIKTIONARY_NOT_FOUND") from exc
            retryable = exc.code in {429, 500, 502, 503, 504}
            if retryable and attempt + 1 < max_attempts:
                retry_after = None
                if exc.headers is not None:
                    try:
                        retry_after = float(exc.headers.get("Retry-After", ""))
                    except (TypeError, ValueError):
                        retry_after = None
                delay = min(
                    max_backoff_seconds,
                    retry_after if retry_after is not None else backoff_seconds * (2 ** attempt) + jitter,
                )
                sleeper(max(0.0, delay))
                continue
            raise WiktionaryClientError(f"WIKTIONARY_HTTP_{exc.code}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            if attempt + 1 < max_attempts:
                sleeper(min(max_backoff_seconds, backoff_seconds * (2 ** attempt) + jitter))
                continue
            raise WiktionaryClientError("WIKTIONARY_TRANSPORT_FAILURE") from exc

    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WiktionaryClientError("WIKTIONARY_INVALID_JSON") from exc
    parsed = payload.get("parse") if isinstance(payload, dict) else None
    if not isinstance(parsed, dict):
        raise WiktionaryClientError("WIKTIONARY_PARSE_MISSING")
    html = parsed.get("text")
    if isinstance(html, dict):
        html = html.get("*")
    if not isinstance(html, str) or not html.strip():
        raise WiktionaryClientError("WIKTIONARY_EMPTY_PAGE")
    revid = parsed.get("revid")
    if not isinstance(revid, int):
        revid = None
    page_uri = f"https://fr.wiktionary.org/wiki/{quote(surface.replace(' ', '_'))}"
    return parse_french_wiktionary_html(
        surface,
        html,
        revision_id=revid,
        source_uri=page_uri,
    )
