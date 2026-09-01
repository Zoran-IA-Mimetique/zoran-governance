from __future__ import annotations

from dataclasses import asdict
from hashlib import sha256
import json
import os
from pathlib import Path
from threading import Lock
from typing import Callable

from components.semantic_color_patterns_v0.wiktionary_parser import (
    WiktionaryEntry,
    WiktionarySense,
)


CACHE_SCHEMA = "zoran.wiktionary-evidence-cache.v1"
CACHE_MAX_ENTRY_BYTES = 5_000_000


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _normalise_query(value: str) -> str:
    query = value.casefold().replace("’", "'").strip()
    if not query or len(query) > 200:
        raise ValueError("invalid Wiktionary cache query")
    return query


def _entry_payload(entry: WiktionaryEntry) -> dict[str, object]:
    return {
        "surface": entry.surface,
        "language": entry.language,
        "revision_id": entry.revision_id,
        "senses": [asdict(sense) for sense in entry.senses],
        "source_uri": entry.source_uri,
    }


def _entry_from_payload(value: object) -> WiktionaryEntry:
    required = {"surface", "language", "revision_id", "senses", "source_uri"}
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError("Wiktionary cache entry schema mismatch")
    if not all(
        isinstance(value[name], str) and value[name]
        for name in ("surface", "language", "source_uri")
    ):
        raise ValueError("Wiktionary cache entry identity invalid")
    revision = value["revision_id"]
    if revision is not None and (
        not isinstance(revision, int) or isinstance(revision, bool)
    ):
        raise ValueError("Wiktionary cache revision invalid")
    raw_senses = value["senses"]
    if not isinstance(raw_senses, list):
        raise ValueError("Wiktionary cache senses invalid")
    senses = []
    for raw in raw_senses:
        if (
            not isinstance(raw, dict)
            or set(raw) != {"pos", "heading", "definition"}
            or not all(isinstance(item, str) and item for item in raw.values())
        ):
            raise ValueError("Wiktionary cache sense schema mismatch")
        senses.append(WiktionarySense(**raw))
    return WiktionaryEntry(
        surface=value["surface"],
        language=value["language"],
        revision_id=revision,
        senses=tuple(senses),
        source_uri=value["source_uri"],
    )


class WiktionaryDiskCache:
    """Content-addressed success cache for lexical evidence.

    The cached revision remains evidence, never truth authority. Transient
    failures are deliberately not cached. Every file is exclusive-create and
    self-hashed so a damaged or rewritten cache entry fails closed.
    """

    def __init__(
        self,
        root: str | Path,
        fetcher: Callable[[str], WiktionaryEntry],
    ) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.fetcher = fetcher
        self._lock = Lock()
        self._hits = 0
        self._misses = 0

    @property
    def cache_hits(self) -> int:
        with self._lock:
            return self._hits

    @property
    def cache_misses(self) -> int:
        with self._lock:
            return self._misses

    def _path(self, query: str) -> Path:
        return self.root / (sha256(query.encode("utf-8")).hexdigest() + ".json")

    def _read(self, path: Path, query: str) -> WiktionaryEntry:
        if path.stat().st_size > CACHE_MAX_ENTRY_BYTES:
            raise ValueError("Wiktionary cache entry exceeds bounded size")
        payload = json.loads(path.read_text(encoding="utf-8"))
        required = {"schema", "query", "entry", "evidence_sha256"}
        if not isinstance(payload, dict) or set(payload) != required:
            raise ValueError("Wiktionary cache schema mismatch")
        core = {name: payload[name] for name in ("schema", "query", "entry")}
        expected = sha256(_canonical_bytes(core)).hexdigest()
        if (
            payload["schema"] != CACHE_SCHEMA
            or payload["query"] != query
            or payload["evidence_sha256"] != expected
        ):
            raise ValueError("Wiktionary cache evidence mismatch")
        return _entry_from_payload(payload["entry"])

    def __call__(self, surface: str) -> WiktionaryEntry:
        query = _normalise_query(surface)
        path = self._path(query)
        if path.exists():
            entry = self._read(path, query)
            with self._lock:
                self._hits += 1
            return entry
        with self._lock:
            self._misses += 1
        entry = self.fetcher(surface)
        core = {
            "schema": CACHE_SCHEMA,
            "query": query,
            "entry": _entry_payload(entry),
        }
        payload = {
            **core,
            "evidence_sha256": sha256(_canonical_bytes(core)).hexdigest(),
        }
        rendered = json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        ) + "\n"
        if len(rendered.encode("utf-8")) > CACHE_MAX_ENTRY_BYTES:
            raise ValueError("Wiktionary cache entry exceeds bounded size")
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(rendered)
                handle.flush()
        except FileExistsError:
            entry = self._read(path, query)
        return entry
