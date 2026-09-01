"""Deterministic read-progress accounting for Zoran🦋.

The tracker never estimates completion. Progress is computed only from a known
finite set of addressable units (PDF pages, document chunks, corpus objects,
archive members, rows, records, etc.). Duplicate reads never increase progress.

If the total is unknown, percentage completion is RETRY rather than guessed.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable, Sequence

PASS = "PASS"
IN_PROGRESS = "IN_PROGRESS"
RETRY = "RETRY"


def _sha(payload: object) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _percent(read_count: int, total_units: int) -> Decimal:
    if total_units <= 0:
        raise ValueError("total_units must be > 0")
    return (Decimal(read_count) * Decimal(100) / Decimal(total_units)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class ReadProgressReceipt:
    object_id: str
    object_type: str
    unit_name: str
    total_units: int | None
    read_units: tuple[int, ...]
    read_count: int
    remaining_count: int | None
    percent: str | None
    status: str
    complete: bool
    cta: str | None
    next_unread_unit: int | None
    receipt_sha256: str

    def as_dict(self) -> dict[str, object]:
        return {
            "component": "zoran.read-progress-v1",
            "version": "1.0.0",
            "object_id": self.object_id,
            "object_type": self.object_type,
            "unit_name": self.unit_name,
            "total_units": self.total_units,
            "read_units": list(self.read_units),
            "read_count": self.read_count,
            "remaining_count": self.remaining_count,
            "percent": self.percent,
            "status": self.status,
            "complete": self.complete,
            "cta": self.cta,
            "next_unread_unit": self.next_unread_unit,
            "receipt_sha256": self.receipt_sha256,
        }

    def user_message(self) -> str:
        label = self.object_type.upper() if self.object_type else "OBJET"
        if self.total_units is None:
            return f"Lecture {label} : RETRY — total inconnu.\nGO"
        unit = self.unit_name
        base = f"Lecture {label} : {self.percent} % — {self.read_count}/{self.total_units} {unit}."
        return base if self.complete else base + "\nGO"


class ReadProgressTracker:
    """Track exact coverage of any finite object through addressable units.

    Unit indexing is 1-based so PDF page numbers and human-visible document
    positions can be used directly.
    """

    def evaluate(
        self,
        *,
        object_id: str,
        object_type: str,
        total_units: int | None,
        read_units: Sequence[int] = (),
        unit_name: str | None = None,
    ) -> ReadProgressReceipt:
        if not isinstance(object_id,str) or not object_id.strip():
            raise ValueError("object_id required")
        if not isinstance(object_type,str) or not object_type.strip():
            raise ValueError("object_type required")
        if unit_name is not None and not isinstance(unit_name,str):
            raise ValueError("unit_name must be a string")
        unit = (unit_name or self.default_unit_name(object_type)).strip()
        if not unit:
            raise ValueError("unit_name required")

        if any(not isinstance(x,int) or isinstance(x,bool) for x in read_units):
            raise ValueError("read unit indexes must be integers")
        normalized = tuple(sorted(set(read_units)))
        if any(x <= 0 for x in normalized):
            raise ValueError("read unit indexes must be >= 1")

        if total_units is None:
            payload = {
                "object_id": object_id,
                "object_type": object_type,
                "unit_name": unit,
                "total_units": None,
                "read_units": list(normalized),
                "read_count": len(normalized),
                "remaining_count": None,
                "percent": None,
                "status": RETRY,
                "complete": False,
                "cta": "GO",
                "next_unread_unit": None,
            }
            return ReadProgressReceipt(receipt_sha256=_sha(payload), **payload)

        if not isinstance(total_units,int) or isinstance(total_units,bool):
            raise ValueError("total_units must be an integer")
        total = total_units
        if total <= 0:
            raise ValueError("total_units must be > 0")
        if any(x > total for x in normalized):
            raise ValueError("read unit index exceeds total_units")

        count = len(normalized)
        complete = count == total
        pct = _percent(count, total)
        read_set=set(normalized)
        next_unread = next((idx for idx in range(1, total + 1) if idx not in read_set), None)
        payload = {
            "object_id": object_id,
            "object_type": object_type,
            "unit_name": unit,
            "total_units": total,
            "read_units": list(normalized),
            "read_count": count,
            "remaining_count": total - count,
            "percent": f"{pct:.2f}",
            "status": PASS if complete else IN_PROGRESS,
            "complete": complete,
            "cta": None if complete else "GO",
            "next_unread_unit": next_unread,
        }
        return ReadProgressReceipt(receipt_sha256=_sha(payload), **payload)

    def next_window(self, receipt: ReadProgressReceipt, *, max_units: int) -> tuple[int, ...]:
        if not isinstance(max_units,int) or isinstance(max_units,bool) or max_units <= 0:
            raise ValueError("max_units must be > 0")
        if receipt.total_units is None:
            return ()
        read = set(receipt.read_units)
        return tuple(idx for idx in range(1, receipt.total_units + 1) if idx not in read)[:max_units]

    @staticmethod
    def default_unit_name(object_type: str) -> str:
        kind = object_type.strip().casefold()
        if kind == "pdf":
            return "pages"
        if kind in {"document", "docx", "txt", "markdown", "md", "html"}:
            return "blocs"
        if kind in {"folder", "directory", "corpus", "collection"}:
            return "objets"
        if kind in {"spreadsheet", "xlsx", "csv", "table"}:
            return "lignes/blocs"
        if kind in {"archive", "zip", "tar"}:
            return "éléments"
        return "unités"


def terminal_read_status(receipt: ReadProgressReceipt) -> tuple[str, str]:
    """Translate progress into the terminal controller's closed status set."""
    if receipt.total_units is None:
        return RETRY, "READING_TOTAL_UNKNOWN"
    if receipt.complete:
        return PASS, "READING_COMPLETE_100_PERCENT"
    return "FAIL", f"READING_INCOMPLETE:{receipt.percent}%"
