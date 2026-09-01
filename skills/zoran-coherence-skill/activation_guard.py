from __future__ import annotations
import base64,hashlib,json,re
from dataclasses import dataclass
from datetime import datetime,timezone,timedelta
from tolerance_skill import Decision

AMYGDALA_ID='ZORAN.AMYGDALA.1'
AMYGDALA_MANIFEST_SHA256='720a4755b34617d7313dbf7552edc05d59dec9334a4de66a2972b5cd3f159682'

def _dt(x:str):
    d=datetime.fromisoformat(x.replace('Z','+00:00')); 
    if d.tzinfo is None: raise ValueError
    return d.astimezone(timezone.utc)

def canonical_payload(d:dict)->bytes: return json.dumps(d,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()

@dataclass(frozen=True)
class AmygdalaLicense:
    amygdala_id:str; manifest_sha256:str; valid_from:str; valid_until:str
@dataclass(frozen=True)
class MonthlyEntitlement:
    license_id:str; installation_sha512:str; valid_from:str; valid_until:str; signature_b64:str
@dataclass(frozen=True)
class ActivationEvaluation:
    decision:Decision; reasons:tuple[str,...]; receipt_sha256:str

class ActivationGuard:
    def __init__(self,public_key_raw:bytes):
        if len(public_key_raw)!=32: raise ValueError('Ed25519 public key must be 32 bytes')
        self.public_key_raw=public_key_raw
    def verify(self,amy:AmygdalaLicense,ent:MonthlyEntitlement, *, expected_license_id:str,expected_installation_sha512:str,now:str)->ActivationEvaluation:
        request={'public_key_sha256':hashlib.sha256(self.public_key_raw).hexdigest(),'amygdala':amy.__dict__,'entitlement':{**ent.__dict__,'signature_b64_sha256':hashlib.sha256(ent.signature_b64.encode()).hexdigest(),'signature_b64':'REDACTED'},'expected_license_id':expected_license_id,'expected_installation_sha512':expected_installation_sha512,'now':now}
        request_sha=hashlib.sha256(canonical_payload(request)).hexdigest()
        finish=lambda decision,reasons:self._f(decision,reasons,request_sha)
        try: current=_dt(now); af,au=_dt(amy.valid_from),_dt(amy.valid_until); ef,eu=_dt(ent.valid_from),_dt(ent.valid_until)
        except Exception:return finish(Decision.RETRY,('ACTIVATION_TIME_INVALID',))
        if amy.amygdala_id!=AMYGDALA_ID or amy.manifest_sha256!=AMYGDALA_MANIFEST_SHA256:return finish(Decision.VETO,('AMYGDALA_IDENTITY_MISMATCH',))
        if not (af<=current<=au):return finish(Decision.VETO,('AMYGDALA_PERIOD_INACTIVE',))
        if au<af or au-af>timedelta(days=367):return finish(Decision.VETO,('AMYGDALA_PERIOD_EXCEEDS_12_MONTHS',))
        if not expected_license_id.strip() or not re.fullmatch(r'[0-9a-f]{128}',expected_installation_sha512):return finish(Decision.RETRY,('EXPECTED_ACTIVATION_IDENTITY_INVALID',))
        if ent.license_id!=expected_license_id or ent.installation_sha512!=expected_installation_sha512:return finish(Decision.VETO,('LICENSE_INSTALLATION_MISMATCH',))
        if not (ef<=current<=eu):return finish(Decision.VETO,('MONTHLY_ENTITLEMENT_INACTIVE',))
        if eu<ef or eu-ef>timedelta(days=32):return finish(Decision.VETO,('ENTITLEMENT_NOT_MONTHLY',))
        payload={'license_id':ent.license_id,'installation_sha512':ent.installation_sha512,'valid_from':ent.valid_from,'valid_until':ent.valid_until}
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        except ImportError:return finish(Decision.RETRY,('CRYPTOGRAPHY_DEPENDENCY_UNAVAILABLE',))
        try:
            signature=base64.b64decode(ent.signature_b64,validate=True)
            if len(signature)!=64:raise ValueError
            Ed25519PublicKey.from_public_bytes(self.public_key_raw).verify(signature,canonical_payload(payload))
        except Exception:return finish(Decision.VETO,('ENTITLEMENT_SIGNATURE_INVALID',))
        return finish(Decision.PASS,('ZORAN_ACTIVATED',))
    def _f(self,d,r,request_sha):
        p={'request_sha256':request_sha,'decision':d.value,'reasons':list(r)}; h=hashlib.sha256(canonical_payload(p)).hexdigest(); return ActivationEvaluation(d,tuple(r),h)
