from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Callable, Iterable

from components.semantic_color_patterns_v0.gma4_teacher_contract import (
    TeacherProposal,
    parse_teacher_json,
    teacher_closed_enums,
    teacher_schema_example,
)

GMA4_MODEL_ID = "gemma-4-26b-a4b-it"


class TeacherContractError(ValueError):
    def __init__(
        self,
        code: str,
        *,
        attempts: int = 1,
        attempt_trace_sha256: str | None = None,
    ) -> None:
        super().__init__(code)
        self.attempts = attempts
        self.attempt_trace_sha256 = attempt_trace_sha256


_CONTRACT_ERROR_CODES = {
    "invalid teacher payload": "TEACHER_INVALID_PAYLOAD",
    "teacher output must be pure JSON": "TEACHER_NOT_PURE_JSON",
    "teacher payload must be an object": "TEACHER_NOT_OBJECT",
    "teacher payload schema mismatch": "TEACHER_SCHEMA_FIELDS",
    "teacher schema mismatch": "TEACHER_SCHEMA_ID",
    "invalid surface": "TEACHER_INVALID_SURFACE",
    "invalid language": "TEACHER_INVALID_LANGUAGE",
    "invalid definition": "TEACHER_INVALID_DEFINITION",
    "needs_external_evidence must be boolean": "TEACHER_INVALID_EVIDENCE_FLAG",
    "unknown POS candidate": "TEACHER_UNKNOWN_POS",
    "unknown semantic frame candidate": "TEACHER_UNKNOWN_SEMANTIC_FRAME",
    "unknown discourse intention candidate": "TEACHER_UNKNOWN_INTENTION",
    "teacher changed requested surface": "TEACHER_CHANGED_SURFACE",
    "teacher changed language": "TEACHER_CHANGED_LANGUAGE",
}


def _contract_error(
    error: ValueError,
    *,
    attempts: int = 1,
    attempt_trace_sha256: str | None = None,
) -> TeacherContractError:
    message = str(error)
    code = _CONTRACT_ERROR_CODES.get(message)
    if code is None:
        if message.startswith("invalid ") and message.endswith(" item"):
            code = "TEACHER_INVALID_LIST_ITEM"
        elif message.endswith(" must be a bounded list"):
            code = "TEACHER_INVALID_BOUNDED_LIST"
        else:
            code = "TEACHER_CONTRACT_REJECTED"
    return TeacherContractError(
        code,
        attempts=attempts,
        attempt_trace_sha256=attempt_trace_sha256,
    )


@dataclass(frozen=True)
class TeacherRequest:
    surface: str
    context: str
    language: str = "fr"
    known_primitives: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.surface.strip() or len(self.surface) > 200:
            raise ValueError("invalid surface")
        if not self.context.strip() or len(self.context) > 8_000:
            raise ValueError("invalid context")
        if not 2 <= len(self.language.strip()) <= 12:
            raise ValueError("invalid language")
        if len(self.known_primitives) > 500:
            raise ValueError("too many known primitives")


@dataclass(frozen=True)
class TeacherReceipt:
    model: str
    prompt_sha256: str
    response_sha256: str
    proposal: TeacherProposal
    provider_attempts: int = 1
    rejected_response_sha256s: tuple[str, ...] = ()
    attempt_trace_sha256: str = ""
    authority: str = "EVIDENCE_ONLY"
    promotion: str = "FORBIDDEN"


def build_teacher_prompt(request: TeacherRequest) -> str:
    primitives = sorted({item.strip() for item in request.known_primitives if item.strip()})
    schema = teacher_schema_example()
    instructions = {
        "role": "GMA4_LANGUAGE_TEACHER_FOR_ZORAN",
        "authority": "EVIDENCE_ONLY_NO_PROMOTION_NO_TRUTH_AUTHORITY",
        "task": [
            "Explain the unknown surface only in the supplied sentence/context.",
            "Prefer already-known Zoran primitives when possible.",
            "Preserve ambiguity instead of forcing one sense.",
            "Semantic frames describe what the expression means; discourse intentions describe what the discourse is doing. Do not confuse them.",
            "Return pure JSON only, with exactly the required schema and no markdown.",
            "The top-level JSON value must be one object: never an array and never a JSON string.",
            "The first non-whitespace character must be { and the last must be }.",
            "Copy request.surface exactly, character for character, into output.surface; never replace it with a lemma, corrected form or paraphrase.",
            "Every POS, semantic frame and discourse intention must be copied exactly from the supplied closed_enums; never invent a synonym or a new label.",
            "When no precise closed label fits, use UNKNOWN from the corresponding enum instead of creating a label.",
            "If context is insufficient, set needs_external_evidence=true.",
        ],
        "request": {
            "surface": request.surface,
            "language": request.language,
            "context": request.context,
            "known_primitives": primitives,
        },
        "closed_enums": teacher_closed_enums(),
        "required_output_example_shape": schema,
    }
    return json.dumps(instructions, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def build_teacher_correction_prompt(
    request: TeacherRequest,
    *,
    previous_error: str,
    attempt: int,
) -> str:
    if not previous_error.startswith("TEACHER_"):
        raise ValueError("invalid teacher correction code")
    if attempt < 2 or attempt > 3:
        raise ValueError("invalid teacher correction attempt")
    payload = json.loads(build_teacher_prompt(request))
    payload["correction"] = {
        "attempt": attempt,
        "previous_output_rejected": previous_error,
        "instruction": (
            "Generate a completely new full proposal. Correct the rejected field, "
            "copy request.surface and request.language exactly, and keep every value "
            "inside the closed schema. Do not explain the correction."
        ),
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


class GMA4TeacherAdapter:
    """Strict adapter around the existing Gemma 4 provider.

    The transport is injected so this learning module never owns API secrets or
    provider authority. In production the transport can be bound to Zoran's
    existing managed Gemma service. Tests can use a deterministic fake.
    """

    def __init__(
        self,
        transport: Callable[[str], str],
        *,
        model: str = GMA4_MODEL_ID,
        max_contract_attempts: int = 2,
    ) -> None:
        if (
            not isinstance(max_contract_attempts, int)
            or isinstance(max_contract_attempts, bool)
            or not 1 <= max_contract_attempts <= 3
        ):
            raise ValueError("invalid max_contract_attempts")
        self._transport = transport
        self._model = model
        self._max_contract_attempts = max_contract_attempts

    def teach(self, request: TeacherRequest) -> TeacherReceipt:
        initial_prompt = build_teacher_prompt(request)
        prompt = initial_prompt
        trace: list[dict[str, str]] = []
        rejected_response_sha256s: list[str] = []
        previous_error: TeacherContractError | None = None
        for attempt in range(1, self._max_contract_attempts + 1):
            try:
                raw = self._transport(prompt)
            except Exception as exc:
                try:
                    setattr(exc, "attempts", attempt)
                except (AttributeError, TypeError):
                    pass
                raise
            prompt_hash = sha256(prompt.encode("utf-8")).hexdigest()
            response_hash = sha256(raw.encode("utf-8")).hexdigest()
            trace.append({
                "prompt_sha256": prompt_hash,
                "response_sha256": response_hash,
            })
            try:
                proposal = parse_teacher_json(raw)
                if proposal.surface.casefold() != request.surface.strip().casefold():
                    raise ValueError("teacher changed requested surface")
                if proposal.language != request.language.strip().lower():
                    raise ValueError("teacher changed language")
            except ValueError as exc:
                trace_hash = sha256(json.dumps(
                    trace,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")).hexdigest()
                previous_error = _contract_error(
                    exc,
                    attempts=attempt,
                    attempt_trace_sha256=trace_hash,
                )
                rejected_response_sha256s.append(response_hash)
                if attempt == self._max_contract_attempts:
                    raise previous_error from exc
                prompt = build_teacher_correction_prompt(
                    request,
                    previous_error=str(previous_error),
                    attempt=attempt + 1,
                )
                continue
            trace_hash = sha256(json.dumps(
                trace,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")).hexdigest()
            return TeacherReceipt(
                model=self._model,
                prompt_sha256=sha256(initial_prompt.encode("utf-8")).hexdigest(),
                response_sha256=response_hash,
                proposal=proposal,
                provider_attempts=attempt,
                rejected_response_sha256s=tuple(rejected_response_sha256s),
                attempt_trace_sha256=trace_hash,
            )
        raise previous_error or TeacherContractError("TEACHER_CONTRACT_REJECTED")
