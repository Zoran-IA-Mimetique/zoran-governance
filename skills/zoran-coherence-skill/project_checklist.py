from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from delivery_reviewer import PASS as REVIEW_PASS, DeliveryReviewVerdict
from terminal_controller import PASS, TerminalVerdict

PENDING='PENDING'
VALIDATED='VALIDATED'
BLOCKED='BLOCKED'
RETRY='RETRY'


def _sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(',', ':'),
            allow_nan=False,
        ).encode('utf-8')
    ).hexdigest()


@dataclass(frozen=True)
class ChecklistItem:
    item_id: str
    title: str
    rationale: str
    state: str=PENDING
    terminal_receipt_sha256: str|None=None
    reviewer_receipt_sha256: str|None=None
    evidence_sha256: str|None=None
    explanation: str|None=None

    def as_dict(self):
        return self.__dict__


@dataclass(frozen=True)
class ProjectContext:
    project_id: str
    objective: str
    notify_progress: bool
    checklist_approved: bool
    checklist_revision: int
    items: tuple[ChecklistItem,...]
    context_sha256: str

    def as_markdown(self):
        lines=[
            f'# Projet — {self.project_id}',
            '',
            f'**Objectif :** {self.objective}',
            f'**Prévenir de l’avancement :** {"Oui" if self.notify_progress else "Non"}',
            f'**Checklist validée par l’utilisateur :** {"Oui" if self.checklist_approved else "Non"}',
            '',
            '## Checklist',
        ]
        for item in self.items:
            lines.append(f'- [{"x" if item.state==VALIDATED else " "}] {item.title} — {item.state}')
            if item.explanation:
                lines.append(f'  - {item.explanation}')
        return '\n'.join(lines)+'\n'


def _build(pid, obj, notify, approved, rev, items):
    if not isinstance(pid,str) or not isinstance(obj,str) or not pid.strip() or not obj.strip() or not items:
        raise ValueError('PROJECT_CONTEXT_INVALID')
    if not isinstance(notify,bool) or not isinstance(approved,bool) or not isinstance(rev,int) or isinstance(rev,bool) or rev<1:
        raise ValueError('PROJECT_CONTEXT_FLAGS_INVALID')
    ids=[item.item_id for item in items]
    if len(ids)!=len(set(ids)) or any(not item.item_id.strip() or not item.title.strip() for item in items):
        raise ValueError('CHECKLIST_ITEMS_INVALID')
    payload={
        'project_id':pid,
        'objective':obj,
        'notify_progress':notify,
        'checklist_approved':approved,
        'checklist_revision':rev,
        'items':[x.as_dict() for x in items],
    }
    return ProjectContext(
        pid,obj,notify,approved,rev,tuple(items),_sha(payload)
    )


def onboarding_cta():
    return {
        'message':'Zoran🦋 peut suivre ce projet avec une checklist et te prévenir quand une étape est réellement validée. Veux-tu être prévenu de l’avancement ?',
        'choices':['Oui','Non'],
    }


def create_project_context(project_id, objective, proposed_items:Sequence[Mapping[str,str]], *, notify_progress):
    return _build(
        project_id,
        objective,
        notify_progress,
        False,
        1,
        [ChecklistItem(str(x['item_id']),str(x['title']),str(x.get('rationale',''))) for x in proposed_items],
    )


def revise_checklist(ctx, items):
    if ctx.checklist_approved:
        raise ValueError('CHECKLIST_ALREADY_APPROVED')
    return _build(
        ctx.project_id,
        ctx.objective,
        ctx.notify_progress,
        False,
        ctx.checklist_revision+1,
        [ChecklistItem(str(x['item_id']),str(x['title']),str(x.get('rationale',''))) for x in items],
    )


def approve_checklist(ctx):
    return _build(
        ctx.project_id,
        ctx.objective,
        ctx.notify_progress,
        True,
        ctx.checklist_revision,
        ctx.items,
    )


def validate_item(
    ctx,
    item_id,
    *,
    terminal_verdict:TerminalVerdict,
    reviewer_verdict:DeliveryReviewVerdict,
    evidence:Mapping[str,Any],
    explanation:str,
    trusted_terminal_receipts:Sequence[str]=(),
    trusted_reviewer_receipts:Sequence[str]=(),
):
    """Close an item only after execution AND delivery conformity both pass."""
    if not ctx.checklist_approved:
        raise ValueError('CHECKLIST_NOT_APPROVED')
    if terminal_verdict.status!=PASS:
        raise ValueError('TERMINAL_PASS_REQUIRED')
    if reviewer_verdict.status!=REVIEW_PASS:
        raise ValueError('DELIVERY_REVIEWER_PASS_REQUIRED')
    if terminal_verdict.receipt_sha256 not in frozenset(trusted_terminal_receipts):
        raise ValueError('TERMINAL_RECEIPT_UNTRUSTED')
    if reviewer_verdict.receipt_sha256 not in frozenset(trusted_reviewer_receipts):
        raise ValueError('REVIEWER_RECEIPT_UNTRUSTED')

    items=[]
    found=False
    for item in ctx.items:
        if item.item_id==item_id:
            found=True
            items.append(
                ChecklistItem(
                    item.item_id,
                    item.title,
                    item.rationale,
                    VALIDATED,
                    terminal_verdict.receipt_sha256,
                    reviewer_verdict.receipt_sha256,
                    _sha(evidence),
                    explanation,
                )
            )
        else:
            items.append(item)
    if not found:
        raise ValueError('CHECKLIST_ITEM_NOT_FOUND')

    updated=_build(
        ctx.project_id,
        ctx.objective,
        ctx.notify_progress,
        True,
        ctx.checklist_revision,
        items,
    )
    msg=None
    if ctx.notify_progress:
        title=next(x for x in updated.items if x.item_id==item_id).title
        msg=f'✅🌱 Zoran🦋 — Étape validée et conforme : {title}. {explanation}'
    return updated,msg


def progress_summary(ctx):
    done=sum(x.state==VALIDATED for x in ctx.items)
    total=len(ctx.items)
    return {
        'done':done,
        'total':total,
        'percent':done*100/total if total else 0,
        'remaining':total-done,
        'context_sha256':ctx.context_sha256,
    }
