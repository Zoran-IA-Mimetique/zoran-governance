from __future__ import annotations
import hashlib,json,os,secrets,stat
from dataclasses import dataclass
from pathlib import Path

DOMAIN=b'ZORAN-INSTALLATION-V1\0'
@dataclass(frozen=True)
class InstallationIdentity:
    license_id:str; installation_sha512:str

def _safe_file(path:Path):
    if path.exists():
        st=path.lstat()
        if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode) or st.st_nlink!=1: raise ValueError('unsafe identity file')

def derive_sha512(license_id:str,seed:bytes)->str:
    if not license_id.strip() or len(seed)<32: raise ValueError('invalid identity material')
    return hashlib.sha512(DOMAIN+license_id.encode()+b'\0'+seed).hexdigest()

def load_or_create(path:str|Path,license_id:str)->InstallationIdentity:
    p=Path(path); p.parent.mkdir(parents=True,exist_ok=True); _safe_file(p)
    if p.exists():
        d=json.loads(p.read_text())
        if d['license_id']!=license_id: raise ValueError('installation already bound to another license')
        seed=bytes.fromhex(d['seed_hex']); calc=derive_sha512(license_id,seed)
        if calc!=d['installation_sha512']: raise ValueError('identity digest mismatch')
        return InstallationIdentity(license_id,calc)
    seed=secrets.token_bytes(32); h=derive_sha512(license_id,seed); d={'license_id':license_id,'seed_hex':seed.hex(),'installation_sha512':h}
    flags=os.O_WRONLY|os.O_CREAT|os.O_EXCL
    fd=os.open(p,flags,0o600)
    try: os.write(fd,json.dumps(d,sort_keys=True).encode()); os.fsync(fd)
    finally: os.close(fd)
    _safe_file(p); return InstallationIdentity(license_id,h)
