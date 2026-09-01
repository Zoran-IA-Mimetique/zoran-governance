from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import re
import subprocess
from typing import Callable, Sequence


COMPONENT_ID = "zoran.repository-head-gate"
VERSION = "1.0.0"
_GIT_OBJECT_ID = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_NETWORK_REMOTE = re.compile(r"^(?:https://|ssh://|git://|git@)[^\s]+$", re.I)


class HeadDecision(str, Enum):
    PASS = "PASS"
    RETRY = "RETRY"
    VETO = "VETO"


@dataclass(frozen=True)
class RepositoryHeadRequest:
    repository: str
    target_branch: str
    remote_name: str = "origin"
    after_full_reclone: bool = False


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str


@dataclass(frozen=True)
class RepositoryHeadReceipt:
    decision: HeadDecision
    reason: str
    repository: str
    target_branch: str
    checked_branch: str
    remote_url: str
    local_head: str
    remote_head: str
    full_clone: bool
    reclone_attempts_remaining: int
    command_evidence: tuple[str, ...]
    receipt_sha256: str


Runner = Callable[[Path, Sequence[str]], CommandResult]


def _canonical_sha(payload: object) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _subprocess_runner(repository: Path, arguments: Sequence[str]) -> CommandResult:
    completed = subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", "-C", str(repository), *arguments],
        env={**os.environ, "GIT_NO_REPLACE_OBJECTS": "1", "GIT_TERMINAL_PROMPT": "0"},
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=90,
        check=False,
    )
    return CommandResult(completed.returncode, completed.stdout.strip())


class RepositoryHeadGate:
    """Fail-closed proof that a full checkout equals the target remote HEAD."""

    def __init__(self, runner: Runner | None = None):
        self._runner = runner or _subprocess_runner

    def evaluate(self, request: RepositoryHeadRequest) -> RepositoryHeadReceipt:
        repository = Path(request.repository).resolve()
        evidence: list[str] = []

        def run(*arguments: str) -> CommandResult:
            result = self._runner(repository, arguments)
            evidence.append(f"git {' '.join(arguments)} => rc={result.returncode};out={result.stdout}")
            return result

        def finish(
            decision: HeadDecision,
            reason: str,
            *,
            checked_branch: str = "",
            remote_url: str = "",
            local_head: str = "",
            remote_head: str = "",
            full_clone: bool = False,
        ) -> RepositoryHeadReceipt:
            attempts_remaining = 0 if request.after_full_reclone or decision is HeadDecision.PASS else 1
            payload = {
                "component": COMPONENT_ID,
                "version": VERSION,
                "decision": decision.value,
                "reason": reason,
                "repository": str(repository),
                "target_branch": request.target_branch,
                "checked_branch": checked_branch,
                "remote_url": remote_url,
                "local_head": local_head,
                "remote_head": remote_head,
                "full_clone": full_clone,
                "reclone_attempts_remaining": attempts_remaining,
                "command_evidence": evidence,
            }
            return RepositoryHeadReceipt(
                decision, reason, str(repository), request.target_branch, checked_branch,
                remote_url, local_head, remote_head, full_clone, attempts_remaining,
                tuple(evidence), _canonical_sha(payload),
            )

        def fail(reason: str, **observed: object) -> RepositoryHeadReceipt:
            decision = HeadDecision.VETO if request.after_full_reclone else HeadDecision.RETRY
            suffix = "AFTER_FULL_RECLONE" if request.after_full_reclone else "FULL_RECLONE_ONCE"
            return finish(decision, f"{reason}:{suffix}", **observed)

        if not repository.is_dir() or not request.target_branch.strip() or not request.remote_name.strip():
            return fail("HEAD_GATE_REQUEST_INVALID")
        inside = run("rev-parse", "--is-inside-work-tree")
        if inside.returncode or inside.stdout != "true":
            return fail("GIT_WORKTREE_REQUIRED")

        shallow = run("rev-parse", "--is-shallow-repository")
        partial_extension = run("config", "--get", "extensions.partialClone")
        promisor = run("config", "--get", f"remote.{request.remote_name}.promisor")
        full_clone = shallow.returncode == 0 and shallow.stdout == "false" and not partial_extension.stdout and promisor.stdout.casefold() != "true"
        if not full_clone:
            return fail("FULL_CLONE_REQUIRED")

        branch = run("branch", "--show-current")
        checked_branch = branch.stdout
        if branch.returncode or checked_branch != request.target_branch:
            return fail("TARGET_BRANCH_NOT_CHECKED_OUT", checked_branch=checked_branch, full_clone=True)

        local = run("rev-parse", "HEAD")
        local_head = local.stdout.casefold()
        if local.returncode or not _GIT_OBJECT_ID.fullmatch(local_head):
            return fail("LOCAL_HEAD_UNREADABLE", checked_branch=checked_branch, local_head=local_head, full_clone=True)

        remote = run("remote", "get-url", request.remote_name)
        remote_url = remote.stdout
        if remote.returncode or not _NETWORK_REMOTE.fullmatch(remote_url) or remote_url.startswith(("file://", "/", "./", "../")):
            return fail("NETWORK_REMOTE_REQUIRED", checked_branch=checked_branch, remote_url=remote_url, local_head=local_head, full_clone=True)

        integrity = run("fsck", "--full", "--no-dangling")
        if integrity.returncode:
            return fail("GIT_OBJECT_INTEGRITY_FAILED", checked_branch=checked_branch, remote_url=remote_url, local_head=local_head, full_clone=True)

        remote_ref = run("ls-remote", "--heads", request.remote_name, f"refs/heads/{request.target_branch}")
        rows = [line.split() for line in remote_ref.stdout.splitlines() if line.strip()]
        remote_head = rows[0][0].casefold() if remote_ref.returncode == 0 and len(rows) == 1 and len(rows[0]) == 2 else ""
        if not _GIT_OBJECT_ID.fullmatch(remote_head):
            return fail("REMOTE_BRANCH_HEAD_UNREADABLE", checked_branch=checked_branch, remote_url=remote_url, local_head=local_head, remote_head=remote_head, full_clone=True)
        if local_head != remote_head:
            return fail("HEAD_REMOTE_DIVERGENCE", checked_branch=checked_branch, remote_url=remote_url, local_head=local_head, remote_head=remote_head, full_clone=True)

        return finish(
            HeadDecision.PASS,
            "FULL_CLONE_TARGET_BRANCH_HEAD_MATCH",
            checked_branch=checked_branch,
            remote_url=remote_url,
            local_head=local_head,
            remote_head=remote_head,
            full_clone=True,
        )


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("repository")
    parser.add_argument("target_branch")
    parser.add_argument("--remote", default="origin")
    parser.add_argument("--after-full-reclone", action="store_true")
    args = parser.parse_args()
    receipt = RepositoryHeadGate().evaluate(RepositoryHeadRequest(args.repository, args.target_branch, args.remote, args.after_full_reclone))
    print(json.dumps({**receipt.__dict__, "decision": receipt.decision.value}, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if receipt.decision is HeadDecision.PASS else 2 if receipt.decision is HeadDecision.RETRY else 3


if __name__ == "__main__":
    raise SystemExit(main())
