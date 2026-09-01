from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Sequence

PASS = 'PASS'
FAIL = 'FAIL'
RETRY = 'RETRY'

COMPONENT_ID = 'ZORAN_DELIVERY_REVIEWER'
VERSION = '2.0.0'

REQUIRED_CATEGORIES = (
    'DONE',
    'OBJECTIVE_CONFORMITY',
    'MULTIFRAME_COHERENCE',
    'CODE_QUALITY',
    'COHERENCE_QUALITY',
    'EVIDENCE_COMPLETENESS',
    'INDEPENDENT_REVIEW',
)


def _canon(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(',', ':'),
        allow_nan=False,
    ).encode('utf-8')


def _sha(value: Any) -> str:
    return hashlib.sha256(_canon(value)).hexdigest()


def _valid_sha(value: str | None) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(c in '0123456789abcdef' for c in value)
    )


@dataclass(frozen=True)
class ReviewCheck:
    check_id: str
    category: str
    status: str
    observed: bool
    evidence_sha256: str | None
    frame_ids: tuple[str, ...]
    objective_clause: str
    detail: str = ''
    observed_defects: int | None = None
    objective_sha256: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            'check_id': self.check_id,
            'category': self.category,
            'status': self.status,
            'observed': self.observed,
            'evidence_sha256': self.evidence_sha256,
            'frame_ids': list(self.frame_ids),
            'objective_clause': self.objective_clause,
            'detail': self.detail,
            'observed_defects': self.observed_defects,
            'objective_sha256': self.objective_sha256,
        }


@dataclass(frozen=True)
class DeliveryReviewRequest:
    deliverable_id: str
    objective: str
    builder_identity: str
    reviewer_identity: str
    scope_files: tuple[str, ...]
    reviewed_files: tuple[str, ...]
    checks: tuple[ReviewCheck, ...]


@dataclass(frozen=True)
class DeliveryReviewVerdict:
    status: str
    reasons: tuple[str, ...]
    categories_checked: tuple[str, ...]
    scope_file_count: int
    reviewed_file_count: int
    observed_code_defects: int | None
    observed_coherence_defects: int | None
    objective_sha256: str
    receipt_sha256: str

    def as_dict(self) -> dict[str, Any]:
        return {
            'component': COMPONENT_ID,
            'version': VERSION,
            'status': self.status,
            'reasons': list(self.reasons),
            'categories_checked': list(self.categories_checked),
            'scope_file_count': self.scope_file_count,
            'reviewed_file_count': self.reviewed_file_count,
            'observed_code_defects': self.observed_code_defects,
            'observed_coherence_defects': self.observed_coherence_defects,
            'objective_sha256': self.objective_sha256,
            'receipt_sha256': self.receipt_sha256,
        }


class DeliveryReviewer:
    """Fail-closed delivery reviewer.

    The engine does not infer semantic truth from prose. It validates a structured
    review contract: every required category must be measured, bound to evidence,
    bound to the requested objective, cover the declared file scope, and contain
    zero observed code/coherence defects inside that scope.
    """

    def evaluate(self, request: DeliveryReviewRequest) -> DeliveryReviewVerdict:
        reasons: list[str] = []
        fail = False
        unknown = False

        deliverable_id = request.deliverable_id.strip()
        objective = request.objective.strip()
        builder = request.builder_identity.strip()
        reviewer = request.reviewer_identity.strip()

        if not deliverable_id:
            reasons.append('DELIVERABLE_ID_MISSING')
            unknown = True
        if not objective:
            reasons.append('OBJECTIVE_MISSING')
            unknown = True
        if not builder or not reviewer:
            reasons.append('REVIEW_IDENTITIES_MISSING')
            unknown = True
        elif builder == reviewer:
            reasons.append('SELF_REVIEW_FORBIDDEN')
            fail = True

        scope = tuple(request.scope_files)
        reviewed = tuple(request.reviewed_files)
        if not scope:
            reasons.append('REVIEW_SCOPE_MISSING')
            unknown = True
        if len(scope) != len(set(scope)):
            reasons.append('REVIEW_SCOPE_DUPLICATE_FILE')
            fail = True
        if len(reviewed) != len(set(reviewed)):
            reasons.append('REVIEWED_SCOPE_DUPLICATE_FILE')
            fail = True
        if any(not self._safe_scope_path(x) for x in scope):
            reasons.append('REVIEW_SCOPE_UNSAFE_PATH')
            fail = True
        if any(not self._safe_scope_path(x) for x in reviewed):
            reasons.append('REVIEWED_SCOPE_UNSAFE_PATH')
            fail = True

        missing_files = sorted(set(scope) - set(reviewed))
        extra_files = sorted(set(reviewed) - set(scope))
        if missing_files:
            reasons.extend(f'FILE_NOT_REVIEWED:{x}' for x in missing_files)
            unknown = True
        if extra_files:
            reasons.extend(f'REVIEWED_FILE_OUTSIDE_SCOPE:{x}' for x in extra_files)
            fail = True

        checks = tuple(request.checks)
        ids = [x.check_id for x in checks]
        if any(not x.strip() for x in ids):
            reasons.append('CHECK_ID_MISSING')
            unknown = True
        if len(ids) != len(set(ids)):
            reasons.append('DUPLICATE_CHECK_ID')
            fail = True

        by_category: dict[str, list[ReviewCheck]] = {}
        for check in checks:
            by_category.setdefault(check.category, []).append(check)

        for category in REQUIRED_CATEGORIES:
            if category not in by_category:
                reasons.append(f'REQUIRED_REVIEW_CATEGORY_MISSING:{category}')
                unknown = True

        for check in checks:
            if check.category not in REQUIRED_CATEGORIES:
                reasons.append(f'UNREGISTERED_REVIEW_CATEGORY:{check.category}')
                fail = True
                continue
            if not check.objective_clause.strip():
                reasons.append(f'OBJECTIVE_BINDING_MISSING:{check.check_id}')
                unknown = True
            if not objective or check.objective_sha256 != hashlib.sha256(objective.encode('utf-8')).hexdigest():
                reasons.append(f'OBJECTIVE_DIGEST_BINDING_INVALID:{check.check_id}')
                unknown = True
            if not check.frame_ids or any(not x.strip() for x in check.frame_ids):
                reasons.append(f'FRAME_BINDING_MISSING:{check.check_id}')
                unknown = True
            if not isinstance(check.observed,bool) or check.observed is not True:
                reasons.append(f'CHECK_NOT_OBSERVED:{check.check_id}')
                unknown = True
                continue
            if not _valid_sha(check.evidence_sha256):
                reasons.append(f'EVIDENCE_RECEIPT_INVALID:{check.check_id}')
                unknown = True
                continue
            if check.status == FAIL:
                reasons.append(f'CHECK_FAIL:{check.check_id}:{check.detail or "UNSPECIFIED"}')
                fail = True
            elif check.status == RETRY:
                reasons.append(f'CHECK_RETRY:{check.check_id}:{check.detail or "UNSPECIFIED"}')
                unknown = True
            elif check.status != PASS:
                reasons.append(f'CHECK_STATUS_INVALID:{check.check_id}:{check.status}')
                unknown = True

        # A multicriteria review must truly use more than one frame.
        multi = by_category.get('MULTIFRAME_COHERENCE', [])
        multi_frames = {f for check in multi for f in check.frame_ids if f.strip()}
        if multi and len(multi_frames) < 2:
            reasons.append('MULTIFRAME_REVIEW_REQUIRES_AT_LEAST_TWO_FRAMES')
            unknown = True

        code_defects = self._defect_count(by_category.get('CODE_QUALITY', ()), 'CODE', reasons)
        coherence_defects = self._defect_count(by_category.get('COHERENCE_QUALITY', ()), 'COHERENCE', reasons)
        if code_defects is None:
            unknown = True
        elif code_defects != 0:
            fail = True
        if coherence_defects is None:
            unknown = True
        elif coherence_defects != 0:
            fail = True

        status = FAIL if fail else (RETRY if unknown else PASS)
        objective_sha = hashlib.sha256(objective.encode('utf-8')).hexdigest() if objective else '0' * 64
        payload = {
            'component': COMPONENT_ID,
            'version': VERSION,
            'deliverable_id': deliverable_id,
            'objective_sha256': objective_sha,
            'builder_identity': builder,
            'reviewer_identity': reviewer,
            'scope_files': list(scope),
            'reviewed_files': list(reviewed),
            'checks': [x.as_dict() for x in checks],
            'status': status,
            'reasons': reasons,
            'observed_code_defects': code_defects,
            'observed_coherence_defects': coherence_defects,
        }
        receipt = _sha(payload)
        return DeliveryReviewVerdict(
            status=status,
            reasons=tuple(reasons),
            categories_checked=tuple(sorted(by_category)),
            scope_file_count=len(scope),
            reviewed_file_count=len(reviewed),
            observed_code_defects=code_defects,
            observed_coherence_defects=coherence_defects,
            objective_sha256=objective_sha,
            receipt_sha256=receipt,
        )

    @staticmethod
    def _defect_count(checks: Sequence[ReviewCheck], prefix: str, reasons: list[str]) -> int | None:
        if not checks:
            return None
        if any(x.observed_defects is None for x in checks):
            reasons.append(f'{prefix}_DEFECT_COUNT_RETRY')
            return None
        values = [x.observed_defects for x in checks]
        if any(not isinstance(x, int) or isinstance(x, bool) or x < 0 for x in values):
            reasons.append(f'{prefix}_DEFECT_COUNT_INVALID')
            return None
        total = sum(values)
        if total:
            reasons.append(f'{prefix}_DEFECTS_OBSERVED:{total}')
        return total

    @staticmethod
    def _safe_scope_path(value: str) -> bool:
        if not isinstance(value, str) or not value or '\\' in value:
            return False
        path = PurePosixPath(value)
        return not path.is_absolute() and '..' not in path.parts and value not in {'.', './'} and path.as_posix() == value
