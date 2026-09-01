from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from math import isfinite
import re
from types import MappingProxyType
from typing import Mapping, Sequence

from tolerance_skill import Decision, TOLERANCE_FAMILIES

COMPONENT_ID = "ZORAN_DECOMPOSITION_CALIBRATION"
VERSION = "11.0.0"


@dataclass(frozen=True)
class PartRule:
    part_id: str
    criticality: str  # critical | high | medium | low
    tolerance_profile_id: str
    required: bool = True


@dataclass(frozen=True)
class DecompositionSchema:
    domain_id: str
    schema_version: str
    parts: tuple[PartRule, ...]

    def __post_init__(self):
        object.__setattr__(self, "parts", tuple(self.parts))


@dataclass(frozen=True)
class CalibrationProfile:
    profile_id: str
    dimension_caps: Mapping[str, float]
    zero_tolerance_dimensions: tuple[str, ...] = ()
    evidence_id: str = ""

    def __post_init__(self):
        object.__setattr__(self, "dimension_caps", MappingProxyType(dict(self.dimension_caps)))
        object.__setattr__(self, "zero_tolerance_dimensions", tuple(self.zero_tolerance_dimensions))


@dataclass(frozen=True)
class DecompositionCalibrationEvaluation:
    decision: Decision
    reasons: tuple[str, ...]
    domain_id: str
    parts: tuple[str, ...]
    profile_ids: tuple[str, ...]
    receipt_sha256: str


class DecompositionCalibrationEngine:
    """Bounded métier decomposition.

    It decomposes only domains for which a schema and calibration profiles were
    explicitly registered. Unknown domains fail closed instead of inventing parts or
    tolerances.
    """

    def __init__(self, schemas: Sequence[DecompositionSchema], profiles: Sequence[CalibrationProfile]):
        schema_items=tuple(schemas); profile_items=tuple(profiles)
        self.schemas = MappingProxyType({s.domain_id: s for s in schema_items})
        self.profiles = MappingProxyType({p.profile_id:CalibrationProfile(p.profile_id,MappingProxyType(dict(p.dimension_caps)),tuple(p.zero_tolerance_dimensions),p.evidence_id) for p in profile_items})
        if len(self.schemas) != len(schema_items) or len(self.profiles) != len(profile_items):
            raise ValueError("duplicate schema/profile id")
        for schema in self.schemas.values():
            ids=[part.part_id for part in schema.parts]
            if not schema.domain_id.strip() or not schema.schema_version.strip() or len(ids)!=len(set(ids)) or any(not x.strip() for x in ids):raise ValueError("invalid decomposition schema")
            for part in schema.parts:
                if part.criticality not in {"critical","high","medium","low"} or not isinstance(part.required,bool) or not part.tolerance_profile_id.strip():raise ValueError("invalid part rule")
        for profile in self.profiles.values():
            if not profile.profile_id.strip() or not re.fullmatch(r"[0-9a-f]{64}",profile.evidence_id) or not profile.dimension_caps:raise ValueError("invalid calibration profile")
            if set(profile.dimension_caps)-set(TOLERANCE_FAMILIES) or len(profile.zero_tolerance_dimensions)!=len(set(profile.zero_tolerance_dimensions)):raise ValueError("invalid calibration dimensions")
            if any(not isinstance(v,(int,float)) or isinstance(v,bool) or not isfinite(float(v)) or v<0 for v in profile.dimension_caps.values()):raise ValueError("invalid calibration caps")
            if any(name not in profile.dimension_caps or profile.dimension_caps[name]!=0 for name in profile.zero_tolerance_dimensions):raise ValueError("invalid zero-tolerance calibration")
        registry={'schemas':[{'domain_id':s.domain_id,'schema_version':s.schema_version,'parts':[p.__dict__ for p in s.parts]} for s in sorted(self.schemas.values(),key=lambda x:x.domain_id)],'profiles':[{'profile_id':p.profile_id,'dimension_caps':dict(sorted(p.dimension_caps.items())),'zero_tolerance_dimensions':list(p.zero_tolerance_dimensions),'evidence_id':p.evidence_id} for p in sorted(self.profiles.values(),key=lambda x:x.profile_id)]}
        self.registry_sha256=hashlib.sha256(json.dumps(registry,sort_keys=True,separators=(',',':')).encode()).hexdigest()

    def evaluate(self, domain_id: str, *, observed_parts: Sequence[str] = ()) -> DecompositionCalibrationEvaluation:
        schema = self.schemas.get(domain_id)
        if schema is None:
            return self._finish(Decision.RETRY, ("DOMAIN_SCHEMA_UNAVAILABLE",), domain_id, (), (),tuple(observed_parts))
        if not schema.parts:
            return self._finish(Decision.RETRY, ("DOMAIN_SCHEMA_EMPTY",), domain_id, (), (),tuple(observed_parts))

        if len(observed_parts)!=len(set(observed_parts)) or any(not isinstance(x,str) or not x.strip() for x in observed_parts):
            return self._finish(Decision.VETO,("OBSERVED_PARTS_INVALID",),domain_id,tuple(p.part_id for p in schema.parts),(),tuple(observed_parts))
        observed = set(observed_parts)
        unknown=sorted(observed-set(p.part_id for p in schema.parts))
        if unknown:return self._finish(Decision.VETO,("OBSERVED_PART_UNREGISTERED",)+tuple(unknown),domain_id,tuple(p.part_id for p in schema.parts),(),tuple(observed_parts))
        missing = [p.part_id for p in schema.parts if p.required and p.part_id not in observed]
        if missing:
            return self._finish(Decision.RETRY, ("REQUIRED_PART_TRACE_PENDING",) + tuple(missing), domain_id, tuple(p.part_id for p in schema.parts), (),tuple(observed_parts))

        profile_ids: list[str] = []
        for part in schema.parts:
            profile = self.profiles.get(part.tolerance_profile_id)
            if profile is None or not profile.evidence_id:
                return self._finish(Decision.RETRY, (f"CALIBRATION_PROFILE_TRACE_PENDING:{part.part_id}",), domain_id, tuple(p.part_id for p in schema.parts), tuple(profile_ids),tuple(observed_parts))
            profile_ids.append(profile.profile_id)

        return self._finish(Decision.PASS, ("DECOMPOSITION_AND_CALIBRATION_RESOLVED",), domain_id, tuple(p.part_id for p in schema.parts), tuple(profile_ids),tuple(observed_parts))

    def _finish(self, decision, reasons, domain_id, parts, profiles,observed_parts):
        payload = {
            "component": COMPONENT_ID,
            "version": VERSION,
            "decision": decision.value,
            "reasons": list(reasons),
            "domain_id": domain_id,
            "registry_sha256":self.registry_sha256,
            "observed_parts":list(observed_parts),
            "parts": list(parts),
            "profile_ids": list(profiles),
        }
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return DecompositionCalibrationEvaluation(decision, tuple(reasons), domain_id, tuple(parts), tuple(profiles), digest)
