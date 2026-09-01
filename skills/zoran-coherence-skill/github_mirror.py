from __future__ import annotations
import hashlib,json,os,re,shutil,stat,tempfile
from dataclasses import dataclass
from pathlib import Path,PurePosixPath
from typing import Mapping,Sequence
from tolerance_skill import Decision

REPO='zorania2025/Zoran-IA-deteriniste'
@dataclass(frozen=True)
class MirrorFile:
    path:str; content:bytes; sha256:str
@dataclass(frozen=True)
class MirrorSnapshot:
    repository:str; commit_sha:str; mode:str; files:tuple[MirrorFile,...]
@dataclass(frozen=True)
class MirrorEvaluation:
    decision:Decision; mode:str|None; commit_sha:str|None; manifest_sha256:str|None; reasons:tuple[str,...]

def _safe_rel(path:str):
    p=PurePosixPath(path)
    if p.is_absolute() or '..' in p.parts or not path or '\\' in path:return False
    return True

def manifest_digest(snapshot:MirrorSnapshot):
    x={'repository':snapshot.repository,'commit_sha':snapshot.commit_sha,'mode':snapshot.mode,'files':[{'path':f.path,'sha256':f.sha256,'size':len(f.content)} for f in sorted(snapshot.files,key=lambda f:f.path)]}
    return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(',',':')).encode()).hexdigest()

class GithubMirror:
    def __init__(self,root:str|Path):self.root=Path(root).resolve(); self.root.mkdir(parents=True,exist_ok=True)
    def install(self,snapshot:MirrorSnapshot,*,max_full_bytes:int,allowlist:Sequence[str]=())->MirrorEvaluation:
        if snapshot.repository!=REPO:return MirrorEvaluation(Decision.VETO,None,None,None,('WRONG_REPOSITORY',))
        if snapshot.mode!='FULL':return MirrorEvaluation(Decision.VETO,None,None,None,('SOURCE_SNAPSHOT_MODE_INVALID',))
        if not isinstance(max_full_bytes,int) or isinstance(max_full_bytes,bool) or max_full_bytes<0:return MirrorEvaluation(Decision.VETO,None,None,None,('INVALID_MAX_FULL_BYTES',))
        if not re.fullmatch(r'[0-9a-f]{40}',snapshot.commit_sha):return MirrorEvaluation(Decision.VETO,None,None,None,('INVALID_COMMIT_SHA',))
        paths=[f.path for f in snapshot.files]
        if len(paths)!=len(set(paths)) or any(not _safe_rel(p) for p in paths):return MirrorEvaluation(Decision.VETO,None,None,None,('UNSAFE_OR_DUPLICATE_PATH',))
        for f in snapshot.files:
            if not isinstance(f.content,bytes) or not re.fullmatch(r'[0-9a-f]{64}',f.sha256) or hashlib.sha256(f.content).hexdigest()!=f.sha256:return MirrorEvaluation(Decision.VETO,None,None,None,(f'FILE_SHA_MISMATCH:{f.path}',))
        total=sum(len(f.content) for f in snapshot.files); mode='FULL' if total<=max_full_bytes else 'TARGETED'
        chosen=list(snapshot.files)
        if mode=='TARGETED':
            allowed=tuple(allowlist)
            if any(not _safe_rel(path.rstrip('/')) for path in allowed):return MirrorEvaluation(Decision.VETO,mode,snapshot.commit_sha,None,('TARGETED_ALLOWLIST_UNSAFE',))
            chosen=[f for f in snapshot.files if any(f.path==a or f.path.startswith(a.rstrip('/')+'/') for a in allowed)]
            if not chosen:return MirrorEvaluation(Decision.RETRY,mode,snapshot.commit_sha,None,('TARGETED_ALLOWLIST_EMPTY',))
            if sum(len(f.content) for f in chosen)>max_full_bytes:return MirrorEvaluation(Decision.RETRY,mode,snapshot.commit_sha,None,('TARGETED_SELECTION_EXCEEDS_BYTE_LIMIT',))
        final=self.root/'current'; stage=Path(tempfile.mkdtemp(prefix='.mirror-',dir=self.root))
        try:
            for f in chosen:
                dest=stage/f.path; dest.parent.mkdir(parents=True,exist_ok=True); dest.write_bytes(f.content)
            snap2=MirrorSnapshot(snapshot.repository,snapshot.commit_sha,mode,tuple(chosen)); digest=manifest_digest(snap2)
            (stage/'MIRROR_MANIFEST.json').write_text(json.dumps({'repository':REPO,'commit_sha':snapshot.commit_sha,'mode':mode,'manifest_sha256':digest,'files':[{'path':f.path,'sha256':f.sha256} for f in sorted(chosen,key=lambda x:x.path)]},sort_keys=True))
            backup=self.root/'previous'
            if backup.exists():shutil.rmtree(backup)
            if final.exists():final.rename(backup)
            stage.rename(final); stage=None
            verified=self.verify(required=True)
            if verified.decision is not Decision.PASS:
                if final.exists():shutil.rmtree(final)
                if backup.exists():backup.rename(final)
                return MirrorEvaluation(verified.decision,mode,snapshot.commit_sha,None,('POST_INSTALL_VERIFICATION_BLOCK',)+verified.reasons)
            return MirrorEvaluation(Decision.PASS,mode,snapshot.commit_sha,digest,('MIRROR_INSTALLED',))
        except Exception:
            if stage and stage.exists():shutil.rmtree(stage,ignore_errors=True)
            return MirrorEvaluation(Decision.RETRY,mode,snapshot.commit_sha,None,('MIRROR_INSTALL_FAILED',))
    def verify(self,*,required:bool)->MirrorEvaluation:
        final=self.root/'current'; mf=final/'MIRROR_MANIFEST.json'
        if not mf.exists():return MirrorEvaluation(Decision.RETRY,None,None,None,(('MIRROR_REQUIRED_ABSENT' if required else 'MIRROR_NOT_REQUIRED'),))
        try:
            if stat.S_ISLNK(mf.lstat().st_mode) or not stat.S_ISREG(mf.lstat().st_mode):raise ValueError
            d=json.loads(mf.read_text())
            if set(d)!={'repository','commit_sha','mode','manifest_sha256','files'}:raise ValueError
            if d['repository']!=REPO or not re.fullmatch(r'[0-9a-f]{40}',d['commit_sha']) or d['mode'] not in {'FULL','TARGETED'} or not re.fullmatch(r'[0-9a-f]{64}',d['manifest_sha256']):raise ValueError
            if not isinstance(d['files'],list):raise ValueError
            expected=set()
            for item in d['files']:
                if set(item)!={'path','sha256'} or not _safe_rel(item['path']) or not re.fullmatch(r'[0-9a-f]{64}',item['sha256']):raise ValueError
                p=final/item['path']; st=p.lstat()
                if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):raise ValueError
                if hashlib.sha256(p.read_bytes()).hexdigest()!=item['sha256']:raise ValueError
                expected.add(item['path'])
            if len(expected)!=len(d['files']):raise ValueError
            actual={str(p.relative_to(final)).replace(os.sep,'/') for p in final.rglob('*') if p.is_file() and p.name!='MIRROR_MANIFEST.json'}
            if actual!=expected:raise ValueError
            pseudo=MirrorSnapshot(d['repository'],d['commit_sha'],d['mode'],tuple(MirrorFile(i['path'],(final/i['path']).read_bytes(),i['sha256']) for i in d['files']))
            if manifest_digest(pseudo)!=d['manifest_sha256']:raise ValueError
            return MirrorEvaluation(Decision.PASS,d['mode'],d['commit_sha'],d['manifest_sha256'],('MIRROR_VALID',))
        except Exception:return MirrorEvaluation(Decision.RETRY,None,None,None,('MIRROR_CORRUPT',))
