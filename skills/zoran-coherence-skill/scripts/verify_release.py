#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_PARTS = {".git", ".zoran", ".pytest_cache", "__pycache__", "dist", "build"}
EXCLUDED_NAMES = {"MANIFEST.sha256", ".coverage"}


def source_files(root: Path):
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if any(part in EXCLUDED_PARTS for part in rel.parts) or path.name in EXCLUDED_NAMES or path.name.endswith("_RESULTS.json"):
            continue
        if path.is_symlink():
            raise RuntimeError(f"SYMLINK_FORBIDDEN:{rel.as_posix()}")
        if path.is_file() and path.suffix not in {".pyc", ".pyo"}:
            yield rel, path


def verify_skill_metadata(root: Path):
    text = (root / "SKILL.md").read_text(encoding="utf-8")
    match = re.match(r"\A---\n(.*?)\n---\n", text, re.S)
    if not match:
        raise RuntimeError("SKILL_FRONTMATTER_MISSING")
    header = match.group(1)
    top_keys = [line.split(":", 1)[0] for line in header.splitlines() if line and not line.startswith(" ")]
    if "name" not in top_keys or "description" not in top_keys or "metadata" not in top_keys:
        raise RuntimeError("SKILL_REQUIRED_FRONTMATTER_MISSING")
    if set(top_keys) - {"name", "description", "license", "allowed-tools", "metadata"}:
        raise RuntimeError("SKILL_UNEXPECTED_FRONTMATTER_KEY")
    if "name: zoran-coherence-skill" not in header:
        raise RuntimeError("SKILL_NAME_INVALID")


def verify_manifest(root: Path):
    rows = (root / "MANIFEST.sha256").read_text().splitlines()
    expected = {}
    for row in rows:
        digest, rel = row.split("  ", 1)
        if not re.fullmatch(r"[0-9a-f]{64}", digest) or rel in expected:
            raise RuntimeError("MANIFEST_ROW_INVALID")
        expected[rel] = digest
    actual = {rel.as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for rel, path in source_files(root)}
    if expected != actual:
        missing = sorted(set(actual) - set(expected))
        extra = sorted(set(expected) - set(actual))
        changed = sorted(key for key in set(actual) & set(expected) if actual[key] != expected[key])
        raise RuntimeError(f"MANIFEST_MISMATCH missing={missing} extra={extra} changed={changed}")
    return len(actual)


def verify_python(root: Path):
    count = 0
    for rel, path in source_files(root):
        if path.suffix == ".py":
            compile(path.read_text(encoding="utf-8"), rel.as_posix(), "exec")
            count += 1
    return count


def _version_tuple(value: str):
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)", value)
    if not match:
        raise RuntimeError(f"DEPENDENCY_VERSION_UNPARSEABLE:{value}")
    return tuple(int(item) for item in match.groups())


def verify_dependencies():
    observed = {name: importlib.metadata.version(name) for name in ("cryptography", "cffi", "pycparser")}
    cryptography_version = _version_tuple(observed["cryptography"])
    if not ((46, 0, 0) <= cryptography_version < (51, 0, 0)):
        raise RuntimeError(f"ED25519_PROVIDER_VERSION_INCOMPATIBLE:{observed['cryptography']}")
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        private = Ed25519PrivateKey.generate()
        message = b"zoran-ed25519-provider-self-test-v1"
        signature = private.sign(message)
        private.public_key().verify(signature, message)
    except Exception as exc:
        raise RuntimeError("ED25519_PROVIDER_SELF_TEST_FAILED") from exc
    return {
        "observed_exact": observed,
        "accepted_cryptography_range": ">=46.0.0,<51.0.0",
        "ed25519_provider_self_test": "PASS",
        "pytest_present": importlib.util.find_spec("pytest") is not None,
        "pytest_required": False,
    }


def run(command, cwd: Path):
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(command, cwd=cwd, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,timeout=180)
    if result.returncode:
        raise RuntimeError(f"COMMAND_FAILED:{command}\n{result.stdout[-4000:]}")
    return result.stdout


def source_test_result(output: str):
    for line in reversed(output.splitlines()):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and value.get("runner") == "zoran-bundled-source-only-v1" and value.get("failed") == 0:
            return value
    raise RuntimeError(f"SOURCE_TEST_RESULT_MISSING:{output[-1000:]}")


def run_source_tests(root: Path, *test_files: str):
    output = run([sys.executable, str(root / "scripts" / "test_runner.py"), str(root), *test_files], root)
    return source_test_result(output)


def inspect_and_extract(archive_path:Path,destination:Path):
    with zipfile.ZipFile(archive_path) as archive:
        names=archive.namelist()
        if not names:raise RuntimeError('ZIP_EMPTY')
        roots={name.split('/',1)[0] for name in names}
        if roots!={'zoran-coherence-skill'}:raise RuntimeError(f'ZIP_ROOT_INVALID:{roots}')
        for info in archive.infolist():
            path=Path(info.filename)
            if path.is_absolute() or '..' in path.parts or '\\' in info.filename:raise RuntimeError(f'ZIP_PATH_UNSAFE:{info.filename}')
            mode=(info.external_attr>>16)&0o170000
            if mode==0o120000:raise RuntimeError(f'ZIP_SYMLINK_FORBIDDEN:{info.filename}')
            if info.file_size>50_000_000 or (info.compress_size and info.file_size/info.compress_size>200):raise RuntimeError(f'ZIP_ENTRY_LIMIT:{info.filename}')
        archive.extractall(destination)
    root=destination/'zoran-coherence-skill'
    verify_manifest(root)
    return root


def certify(full: bool):
    verify_skill_metadata(ROOT)
    checks = {
        "skill_metadata": "PASS",
        "manifest_files": verify_manifest(ROOT),
        "python_files_compiled": verify_python(ROOT),
        "dependencies": verify_dependencies(),
    }
    with tempfile.TemporaryDirectory(prefix="zoran-cert-") as tmp:
        temp=Path(tmp); zip_a=temp/'release-a.zip'; zip_b=temp/'release-b.zip'
        run([sys.executable,str(ROOT/'scripts'/'build_release.py'),'--output',str(zip_a)],ROOT)
        run([sys.executable,str(ROOT/'scripts'/'build_release.py'),'--output',str(zip_b)],ROOT)
        sha_a=hashlib.sha256(zip_a.read_bytes()).hexdigest(); sha_b=hashlib.sha256(zip_b.read_bytes()).hexdigest()
        if sha_a!=sha_b or zip_a.read_bytes()!=zip_b.read_bytes():raise RuntimeError('NON_DETERMINISTIC_RELEASE_BUILD')
        checks['deterministic_zip_sha256']=sha_a
        copy_a=inspect_and_extract(zip_a,temp/'extract-a'); copy_b=inspect_and_extract(zip_b,temp/'extract-b')
        checks['safe_extracted_replays']=2
        validator=Path(os.environ.get('ZORAN_QUICK_VALIDATE','/root/.codex/skills/.system/skill-creator/scripts/quick_validate.py'))
        if validator.exists():
            run([sys.executable,str(validator),str(copy_a)],copy_a); checks['official_quick_validate']='PASS'
        else:
            raise RuntimeError('OFFICIAL_QUICK_VALIDATE_REQUIRED')
        adversarial_a=run_source_tests(copy_a,"test_audit_regressions_v14.py")
        adversarial_b=run_source_tests(copy_b,"test_audit_regressions_v14.py")
        checks["adversarial_tests_passed_per_extract"] = [adversarial_a["passed"],adversarial_b["passed"]]
        phenomenal_a=run_source_tests(copy_a,"test_phenomenal_coherence.py")
        phenomenal_b=run_source_tests(copy_b,"test_phenomenal_coherence.py")
        checks["phenomenal_tests_passed_per_extract"] = [phenomenal_a["passed"],phenomenal_b["passed"]]
        semantic_a=run_source_tests(copy_a,"test_repository_head_gate.py","test_structural_reasoning_gate.py","test_v20_zmos_structural_campaign.py","test_zmos_writer_coordination.py","test_v21_release_audit.py","test_semantic_non_conflation.py","test_robot_handoff_guard.py","test_question_reformulation_gate.py","test_proposition_coherence_gate.py","test_contrastive_corpus_gate.py","test_raw_text_coherence_gate.py","test_execution_governor.py","test_claim_evidence_gate.py","test_batch_learning_runtime_contract.py","test_host_session_guard.py","test_host_truth_guard.py","test_phenomenal_resource_gate.py","test_blind_eval.py")
        semantic_b=run_source_tests(copy_b,"test_repository_head_gate.py","test_structural_reasoning_gate.py","test_v20_zmos_structural_campaign.py","test_zmos_writer_coordination.py","test_v21_release_audit.py","test_semantic_non_conflation.py","test_robot_handoff_guard.py","test_question_reformulation_gate.py","test_proposition_coherence_gate.py","test_contrastive_corpus_gate.py","test_raw_text_coherence_gate.py","test_execution_governor.py","test_claim_evidence_gate.py","test_batch_learning_runtime_contract.py","test_host_session_guard.py","test_host_truth_guard.py","test_phenomenal_resource_gate.py","test_blind_eval.py")
        checks["semantic_claim_session_execution_and_robot_tests_passed_per_extract"] = [semantic_a["passed"],semantic_b["passed"]]
        checks["source_only_runner"] = "PASS_WITHOUT_PYTEST"
        if full:
            suite_a=run_source_tests(copy_a)
            suite_b=run_source_tests(copy_b)
            checks["full_tests_passed_per_extract"] = [suite_a["passed"],suite_b["passed"]]
            campaigns = {}
            for script, result_name in (
                ("campaign.py", "CAMPAIGN_RESULTS.json"),
                ("progress_campaign.py", "PROGRESS_CAMPAIGN_RESULTS.json"),
                ("exhaustive_17d_campaign.py", "EXHAUSTIVE_17D_RESULTS.json"),
                ("exhaustive_composition_campaign.py", "EXHAUSTIVE_COMPOSITION_RESULTS.json"),
                ("phenomenal_coherence_campaign.py", "PHENOMENAL_COHERENCE_CAMPAIGN_RESULTS.json"),
                ("semantic_non_conflation_campaign.py", "SEMANTIC_NON_CONFLATION_CAMPAIGN_RESULTS.json"),
            ):
                run([sys.executable, script], copy_a)
                campaigns[script] = json.loads((copy_a / result_name).read_text())
            sota_output=copy_a/"SOTA_CLOSURE_CAMPAIGN_CERTIFICATE.json"
            run([sys.executable,"scripts/run_sota_closure_campaign.py","--cases-per-category","1000","--output",str(sota_output)],copy_a)
            campaigns["scripts/run_sota_closure_campaign.py"] = json.loads(sota_output.read_text())
            v17_output=copy_a/"V17_HALLUCINATION_CLOSURE_CAMPAIGN_CERTIFICATE.json"
            run([sys.executable,"scripts/run_v17_hallucination_campaign.py","--cases-per-category","1000","--output",str(v17_output)],copy_a)
            campaigns["scripts/run_v17_hallucination_campaign.py"] = json.loads(v17_output.read_text())
            v18_output=copy_a/"V18_PROPOSITION_CAMPAIGN_CERTIFICATE.json"
            run([sys.executable,"scripts/run_v18_proposition_campaign.py","--cases-per-category","1000","--output",str(v18_output)],copy_a)
            campaigns["scripts/run_v18_proposition_campaign.py"] = json.loads(v18_output.read_text())
            v19_output=copy_a/"V19_RAW_TEXT_CAMPAIGN_CERTIFICATE.json"
            run([sys.executable,"scripts/run_v19_raw_text_campaign.py","--cases-per-category","1000","--output",str(v19_output)],copy_a)
            campaigns["scripts/run_v19_raw_text_campaign.py"] = json.loads(v19_output.read_text())
            execution_output=copy_a/"EXECUTION_GOVERNOR_CAMPAIGN_CERTIFICATE.json"
            run([sys.executable,"scripts/run_execution_governor_campaign.py","--cases-per-category","100","--output",str(execution_output)],copy_a)
            campaigns["scripts/run_execution_governor_campaign.py"] = json.loads(execution_output.read_text())
            v20_output=copy_a/"V20_ZMOS_STRUCTURAL_CAMPAIGN_CERTIFICATE.json"
            run([sys.executable,"scripts/run_v20_zmos_structural_campaign.py","--cases-per-category","1000","--output",str(v20_output)],copy_a)
            campaigns["scripts/run_v20_zmos_structural_campaign.py"] = json.loads(v20_output.read_text())
            checks["campaigns"] = campaigns
    return {
        "component": "ZORAN_DETERMINISTIC_RELEASE_CERTIFIER",
        "version": "9.0.0",
        "verdict": "PASS",
        "checks": checks,
        "certification_scope": "DETERMINISTIC_LOCAL_SOFTWARE_ARTIFACT",
        "robot_promotion_authority": "PINNED_EXTERNAL_CERTIFICATE_REQUIRED",
        "source_only_clean_extraction_replay": "PASS",
        "excluded_claims": [
            "organizational_third_party_independence",
            "public_open_world_performance",
            "network_isolated_fresh_dependency_install",
            "scientific_universality",
            "real_planetary_benefit",
        ],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = certify(args.full)
    raw = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.output:
        args.output.write_text(raw, encoding="utf-8")
    print(raw, end="")


if __name__ == "__main__":
    main()
