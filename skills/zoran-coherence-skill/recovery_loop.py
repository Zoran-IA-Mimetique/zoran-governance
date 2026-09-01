from __future__ import annotations
from dataclasses import dataclass
from typing import Callable,Any
from terminal_controller import PASS,FAIL,RETRY,TerminalVerdict,RecoveryDirective
from blockage_watchdog import BlockageWatchdog, LoopSignal, STUCK, RESTART_MESSAGE

@dataclass(frozen=True)
class CycleResult:
    terminal:TerminalVerdict
    product:Any=None
    state_fingerprint:str|None=None
    action_fingerprint:str|None=None
    progress_fingerprint:str|None=None
    error_code:str|None=None
    checkpoint:str|None=None

@dataclass(frozen=True)
class RecoveryResult:
    status:str
    attempts:int
    product:Any
    terminal:TerminalVerdict
    user_action:str|None=None
    connector:str|None=None
    resume_checkpoint:str|None=None
    watchdog_receipt_sha256:str|None=None
    execution_state:str|None=None
    execution_governor_receipt_sha256:str|None=None

Cycle=Callable[[int],CycleResult]
Repair=Callable[[RecoveryDirective,int],bool]
ExecutionGuard=Callable[[CycleResult,int],Any]

class BoundedRecoveryLoop:
    """Reruns the complete cycle after a terminal alarm; never resumes mid-chain."""
    def __init__(self,max_attempts:int=3,watchdog:BlockageWatchdog|None=None):
        if not isinstance(max_attempts,int) or max_attempts<1:raise ValueError('INVALID_MAX_ATTEMPTS')
        self.max_attempts=max_attempts
        self.watchdog=watchdog or BlockageWatchdog()
    def run(self,cycle:Cycle,repair:Repair,execution_guard:ExecutionGuard|None=None)->RecoveryResult:
        last=None
        signals:list[LoopSignal]=[]
        for attempt in range(1,self.max_attempts+1):
            result=cycle(attempt); last=result
            governed=execution_guard(result,attempt) if execution_guard is not None else None
            execution_state=getattr(governed,'execution_state',None)
            governor_receipt=getattr(governed,'receipt_sha256',None)
            if execution_state in {'WAIT_EXTERNAL','STOP'}:
                action='Attente externe terminale; aucune relance automatique.' if execution_state=='WAIT_EXTERNAL' else 'Exécution arrêtée par le budget global.'
                return RecoveryResult(result.terminal.status,attempt,None,result.terminal,action,None,None,None,execution_state,governor_receipt)
            if result.terminal.status==PASS:
                if governed is not None and execution_state!='DONE':
                    return RecoveryResult(RETRY,attempt,None,result.terminal,'Le gouverneur persistant n’a pas confirmé DONE.',None,None,None,'STOP',governor_receipt)
                return RecoveryResult(PASS,attempt,result.product,result.terminal,None,None,None,None,'DONE',governor_receipt)
            if governed is not None and execution_state!='CONTINUE':
                return RecoveryResult(RETRY,attempt,None,result.terminal,'État d’exécution non autorisé.',None,None,None,'STOP',governor_receipt)
            signal=LoopSignal(
                cycle=attempt,
                state_fingerprint=result.state_fingerprint,
                action_fingerprint=result.action_fingerprint,
                progress_fingerprint=result.progress_fingerprint,
                error_code=result.error_code or (result.terminal.reasons[0] if result.terminal.reasons else None),
                checkpoint=result.checkpoint,
                terminal_receipt_sha256=result.terminal.receipt_sha256,
            )
            wd=self.watchdog.evaluate(signals,signal)
            if wd.status==STUCK:
                return RecoveryResult(RETRY,attempt,None,result.terminal,RESTART_MESSAGE,None,wd.resume_checkpoint,wd.receipt_sha256,'STOP',governor_receipt)
            signals.append(signal)
            directives=result.terminal.recovery
            if not directives:
                return RecoveryResult(result.terminal.status,attempt,None,result.terminal,None,None,None,None,'STOP',governor_receipt)
            # User/connector rights are never bypassed automatically.
            external=next((d for d in directives if d.owner in {'USER','CONNECTOR'}),None)
            if external is not None:
                return RecoveryResult(RETRY,attempt,None,result.terminal,external.action,external.connector,None,None,'WAIT_EXTERNAL',governor_receipt)
            changed=False
            for directive in directives:
                changed=repair(directive,attempt) or changed
            if not changed:
                return RecoveryResult(RETRY,attempt,None,result.terminal,'Aucune correction matérielle nouvelle; intervention requise.',None,None,None,'STOP',governor_receipt)
        assert last is not None
        return RecoveryResult(RETRY,self.max_attempts,None,last.terminal,'Nombre maximal de reprises atteint.',None,None,None,'STOP',None)
