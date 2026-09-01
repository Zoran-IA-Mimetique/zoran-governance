from __future__ import annotations

from pathlib import Path

from repository_head_gate import CommandResult, HeadDecision, RepositoryHeadGate, RepositoryHeadRequest


HEAD = "1" * 40
OTHER = "2" * 40


class FakeGit:
    def __init__(self, *, branch="main", local=HEAD, remote=HEAD, shallow=False, remote_url="https://github.com/example/repo.git"):
        self.branch = branch
        self.local = local
        self.remote = remote
        self.shallow = shallow
        self.remote_url = remote_url

    def __call__(self, repository: Path, arguments):
        key = tuple(arguments)
        outputs = {
            ("rev-parse", "--is-inside-work-tree"): "true",
            ("rev-parse", "--is-shallow-repository"): "true" if self.shallow else "false",
            ("config", "--get", "extensions.partialClone"): "",
            ("config", "--get", "remote.origin.promisor"): "",
            ("branch", "--show-current"): self.branch,
            ("rev-parse", "HEAD"): self.local,
            ("remote", "get-url", "origin"): self.remote_url,
            ("fsck", "--full", "--no-dangling"): "",
            ("ls-remote", "--heads", "origin", "refs/heads/main"): f"{self.remote}\trefs/heads/main",
        }
        if key not in outputs:
            return CommandResult(1, "unknown command")
        optional_missing = key in {
            ("config", "--get", "extensions.partialClone"),
            ("config", "--get", "remote.origin.promisor"),
        }
        return CommandResult(1 if optional_missing else 0, outputs[key])


def evaluate(fake: FakeGit, *, after_reclone=False):
    return RepositoryHeadGate(fake).evaluate(RepositoryHeadRequest(".", "main", after_full_reclone=after_reclone))


def test_full_clone_checked_out_branch_and_equal_remote_head_pass():
    result = evaluate(FakeGit())
    assert result.decision is HeadDecision.PASS
    assert result.local_head == result.remote_head == HEAD


def test_shallow_clone_requires_exactly_one_full_reclone_then_vetoes():
    first = evaluate(FakeGit(shallow=True))
    second = evaluate(FakeGit(shallow=True), after_reclone=True)
    assert first.decision is HeadDecision.RETRY and first.reclone_attempts_remaining == 1
    assert second.decision is HeadDecision.VETO and second.reclone_attempts_remaining == 0


def test_target_branch_mismatch_is_not_an_anchor():
    assert evaluate(FakeGit(branch="feature")).reason.startswith("TARGET_BRANCH_NOT_CHECKED_OUT")


def test_local_and_remote_head_divergence_is_rejected():
    result = evaluate(FakeGit(remote=OTHER))
    assert result.decision is HeadDecision.RETRY
    assert result.local_head == HEAD and result.remote_head == OTHER


def test_local_or_caller_fabricated_remote_is_rejected():
    result = evaluate(FakeGit(remote_url="file:///tmp/fabricated.git"))
    assert result.reason.startswith("NETWORK_REMOTE_REQUIRED")


def test_receipt_is_deterministic_for_identical_observations():
    assert evaluate(FakeGit()).receipt_sha256 == evaluate(FakeGit()).receipt_sha256
