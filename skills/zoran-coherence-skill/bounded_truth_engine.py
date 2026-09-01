"""Zoran🦋 bounded-truth verification.

The engine never claims absolute truth. It evaluates how far a claim is
supported by the best actually retrieved and verified sources available at T.
It does not perform network I/O itself: the host executes the search plan and
returns source receipts.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Mapping, Sequence


class SourceKind(str, Enum):
    OFFICIAL_PRIMARY = 'OFFICIAL_PRIMARY'
    PEER_REVIEWED_PRIMARY = 'PEER_REVIEWED_PRIMARY'
    PEER_REVIEWED_REVIEW = 'PEER_REVIEWED_REVIEW'
    INDEPENDENT_REPLICATION = 'INDEPENDENT_REPLICATION'
    ARXIV_PREPRINT = 'ARXIV_PREPRINT'
    REPUTABLE_SECONDARY = 'REPUTABLE_SECONDARY'
    OTHER = 'OTHER'


class Relation(str, Enum):
    SUPPORTS = 'SUPPORTS'
    CONTRADICTS = 'CONTRADICTS'
    NEUTRAL = 'NEUTRAL'


class BoundedTruthStatus(str, Enum):
    STRONGLY_SUPPORTED = 'BOUNDED_TRUTH_STRONGLY_SUPPORTED'
    SUPPORTED = 'BOUNDED_TRUTH_SUPPORTED'
    PROVISIONAL = 'BOUNDED_TRUTH_PROVISIONAL'
    CONTESTED = 'BOUNDED_TRUTH_CONTESTED'
    RETRY = 'RETRY'


@dataclass(frozen=True)
class SourceEvidence:
    source_id: str
    source_kind: SourceKind
    relation: Relation
    independent_group: str
    text_sha256: str
    retrieved: bool = True
    provenance_verified: bool = True
    current_for_claim: bool = True

    @classmethod
    def from_mapping(cls, raw: Mapping[str, object]) -> 'SourceEvidence':
        def strict_bool(name: str, default: bool) -> bool:
            value = raw.get(name, default)
            if not isinstance(value, bool):
                raise ValueError(f'{name} must be bool')
            return value
        source_id=raw['source_id']; independent_group=raw['independent_group']; text_sha256=raw['text_sha256']
        if not isinstance(source_id,str) or not isinstance(independent_group,str) or not isinstance(text_sha256,str):
            raise ValueError('source identifiers and digest must be strings')
        source_kind=raw['source_kind']; relation=raw['relation']
        return cls(
            source_id=source_id,
            source_kind=source_kind if isinstance(source_kind,SourceKind) else SourceKind(source_kind),
            relation=relation if isinstance(relation,Relation) else Relation(relation),
            independent_group=independent_group,
            text_sha256=text_sha256,
            retrieved=strict_bool('retrieved', True),
            provenance_verified=strict_bool('provenance_verified', True),
            current_for_claim=strict_bool('current_for_claim', True),
        )


@dataclass(frozen=True)
class BoundedTruthReceipt:
    status: BoundedTruthStatus
    code: str
    claim_sha256: str
    supporting_ids: tuple[str, ...]
    contradicting_ids: tuple[str, ...]
    neutral_ids: tuple[str, ...]
    independent_support_groups: tuple[str, ...]
    strongest_support_kind: str | None
    strongest_contradiction_kind: str | None
    limitations: tuple[str, ...]
    receipt_sha256: str


_STRENGTH = {
    SourceKind.OFFICIAL_PRIMARY: 6,
    SourceKind.INDEPENDENT_REPLICATION: 6,
    SourceKind.PEER_REVIEWED_PRIMARY: 5,
    SourceKind.PEER_REVIEWED_REVIEW: 5,
    SourceKind.ARXIV_PREPRINT: 3,
    SourceKind.REPUTABLE_SECONDARY: 2,
    SourceKind.OTHER: 1,
}


def _sha_text(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _canonical_sha(payload: Mapping[str, object]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    return _sha_text(raw)


def build_search_plan(*, scientific: bool, time_sensitive: bool) -> tuple[str, ...]:
    """Deterministic source classes the host should try, in order."""
    plan = ['OFFICIAL_OR_PRIMARY_SOURCE']
    if scientific:
        plan.extend(('PEER_REVIEWED_LITERATURE', 'INDEPENDENT_REPLICATION', 'ARXIV_PREPRINTS'))
    if time_sensitive:
        plan.append('CURRENT_OFFICIAL_SOURCE')
    plan.append('REPUTABLE_SECONDARY_CROSSCHECK')
    return tuple(plan)


def evaluate_bounded_truth(
    claim: str,
    evidence: Sequence[SourceEvidence | Mapping[str, object]],
    *,
    time_sensitive: bool = False,
) -> BoundedTruthReceipt:
    evidence_items=tuple(evidence)
    def bind(raw):
        if isinstance(raw,SourceEvidence):
            return {'source_id':raw.source_id,'source_kind':raw.source_kind.value,'relation':raw.relation.value,'independent_group':raw.independent_group,'text_sha256':raw.text_sha256,'retrieved':raw.retrieved,'provenance_verified':raw.provenance_verified,'current_for_claim':raw.current_for_claim}
        if isinstance(raw,Mapping):
            return {str(k):(v.value if isinstance(v,Enum) else v if isinstance(v,(str,int,bool,type(None))) else repr(v)) for k,v in sorted(raw.items(),key=lambda item:str(item[0]))}
        return {'invalid_input':repr(raw)}
    evidence_binding=[bind(raw) for raw in evidence_items]
    evidence_binding.sort(key=lambda item:json.dumps(item,ensure_ascii=False,sort_keys=True,separators=(',',':'),default=repr))
    request_sha=_canonical_sha({'claim_sha256':_sha_text(claim if isinstance(claim,str) else repr(claim)),'time_sensitive':time_sensitive if isinstance(time_sensitive,bool) else repr(time_sensitive),'evidence':evidence_binding})
    normalized: list[SourceEvidence] = []
    limitations: list[str] = []
    if not isinstance(time_sensitive,bool):
        limitations.append('TIME_SENSITIVE_FLAG_INVALID')
    if not isinstance(claim, str) or not claim.strip():
        limitations.append('CLAIM_MISSING')
    raw_ids: list[str] = []
    for raw in evidence_items:
        try:
            raw_ids.append(raw.source_id if isinstance(raw, SourceEvidence) else str(raw['source_id']))
        except Exception:
            continue
    duplicate_ids = {source_id for source_id in raw_ids if raw_ids.count(source_id) > 1}
    if duplicate_ids:
        limitations.extend(f'DUPLICATE_SOURCE_ID:{source_id}' for source_id in sorted(duplicate_ids))
    for raw in evidence_items:
        try:
            item = raw if isinstance(raw, SourceEvidence) else SourceEvidence.from_mapping(raw)
        except Exception:
            limitations.append('INVALID_SOURCE_RECEIPT')
            continue
        if item.source_id in duplicate_ids:
            continue
        if (
            not item.source_id.strip()
            or not item.independent_group.strip()
            or len(item.text_sha256) != 64
            or any(c not in '0123456789abcdef' for c in item.text_sha256)
            or not isinstance(item.retrieved, bool)
            or not isinstance(item.provenance_verified, bool)
            or not isinstance(item.current_for_claim, bool)
        ):
            limitations.append('INVALID_SOURCE_RECEIPT')
            continue
        if not item.retrieved:
            limitations.append(f'SOURCE_NOT_RETRIEVED:{item.source_id}')
            continue
        if not item.provenance_verified:
            limitations.append(f'PROVENANCE_UNVERIFIED:{item.source_id}')
            continue
        if time_sensitive and not item.current_for_claim:
            limitations.append(f'SOURCE_STALE_FOR_CLAIM:{item.source_id}')
            continue
        normalized.append(item)

    claim_sha = _sha_text(claim if isinstance(claim, str) else '')
    supports = tuple(sorted((x for x in normalized if x.relation is Relation.SUPPORTS), key=lambda x: x.source_id))
    contradicts = tuple(sorted((x for x in normalized if x.relation is Relation.CONTRADICTS), key=lambda x: x.source_id))
    neutrals = tuple(sorted((x for x in normalized if x.relation is Relation.NEUTRAL), key=lambda x: x.source_id))

    def strongest(items: Iterable[SourceEvidence]) -> SourceEvidence | None:
        seq = tuple(items)
        if not seq:
            return None
        return max(seq, key=lambda x: (_STRENGTH[x.source_kind], x.source_kind.value, x.source_id))

    strongest_support = strongest(supports)
    strongest_contra = strongest(contradicts)
    support_groups = tuple(sorted({x.independent_group for x in supports}))
    sha_groups: dict[str, set[str]] = {}
    for item in normalized:
        sha_groups.setdefault(item.text_sha256, set()).add(item.independent_group)
    reused = sorted(sha for sha, groups in sha_groups.items() if len(groups) > 1)
    if reused:
        limitations.append('CONTENT_DIGEST_REUSED_ACROSS_INDEPENDENCE_GROUPS')

    if not isinstance(time_sensitive,bool):
        status = BoundedTruthStatus.RETRY
        code = 'TIME_SENSITIVE_FLAG_INVALID'
    elif not isinstance(claim, str) or not claim.strip():
        status = BoundedTruthStatus.RETRY
        code = 'CLAIM_MISSING'
    elif contradicts and strongest_contra is not None and (
        strongest_support is None or _STRENGTH[strongest_contra.source_kind] >= _STRENGTH[strongest_support.source_kind]
    ):
        status = BoundedTruthStatus.CONTESTED
        code = 'STRONG_CONTRADICTION_PRESERVED'
        limitations.append('CONTRADICTION_REQUIRES_EXPLICIT_DISCLOSURE')
    elif not supports:
        status = BoundedTruthStatus.RETRY
        code = 'NO_VERIFIED_SUPPORT'
    else:
        support_strength = _STRENGTH[strongest_support.source_kind] if strongest_support else 0
        # Distinct text digests are a necessary anti-aliasing check. They are not,
        # by themselves, proof of institutional independence.
        high_grade_roots = {x.text_sha256 for x in supports if _STRENGTH[x.source_kind] >= 5}
        if support_strength >= 5 and len(high_grade_roots) >= 2 and len(support_groups) >= 2 and not contradicts:
            status = BoundedTruthStatus.STRONGLY_SUPPORTED
            code = 'MULTIPLE_INDEPENDENT_HIGH_GRADE_SOURCES'
        elif support_strength >= 5 or len(support_groups) >= 2:
            status = BoundedTruthStatus.SUPPORTED
            code = 'VERIFIED_SUPPORT_WITH_BOUNDS'
        else:
            status = BoundedTruthStatus.PROVISIONAL
            code = 'LIMITED_OR_PREPRINT_ONLY_SUPPORT'
            limitations.append('PROVISIONAL_EVIDENCE_ONLY')

    if supports and all(x.source_kind is SourceKind.ARXIV_PREPRINT for x in supports):
        status = BoundedTruthStatus.PROVISIONAL
        code = 'ARXIV_ONLY_IS_PREPRINT_EVIDENCE'
        limitations.append('PREPRINT_NOT_PEER_REVIEWED_BY_DEFAULT')

    if supports:
        limitations.append('INDEPENDENCE_GROUPS_ARE_PROVENANCE_ATTESTATIONS')

    body: dict[str, object] = {
        'request_sha256': request_sha,
        'status': status.value,
        'code': code,
        'claim_sha256': claim_sha,
        'supporting_ids': [x.source_id for x in supports],
        'contradicting_ids': [x.source_id for x in contradicts],
        'neutral_ids': [x.source_id for x in neutrals],
        'independent_support_groups': list(support_groups),
        'strongest_support_kind': strongest_support.source_kind.value if strongest_support else None,
        'strongest_contradiction_kind': strongest_contra.source_kind.value if strongest_contra else None,
        'limitations': sorted(set(limitations)),
    }
    return BoundedTruthReceipt(
        status=status,
        code=code,
        claim_sha256=claim_sha,
        supporting_ids=tuple(body['supporting_ids']),
        contradicting_ids=tuple(body['contradicting_ids']),
        neutral_ids=tuple(body['neutral_ids']),
        independent_support_groups=tuple(body['independent_support_groups']),
        strongest_support_kind=body['strongest_support_kind'],
        strongest_contradiction_kind=body['strongest_contradiction_kind'],
        limitations=tuple(body['limitations']),
        receipt_sha256=_canonical_sha(body),
    )
