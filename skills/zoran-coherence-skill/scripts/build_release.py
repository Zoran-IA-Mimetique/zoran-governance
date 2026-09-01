#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = "zoran-coherence-skill"
EXCLUDED_PARTS = {".git", ".zoran", ".pytest_cache", "__pycache__", "dist", "build"}
EXCLUDED_NAMES = {"MANIFEST.sha256", ".coverage"}


def release_files():
    for path in sorted(ROOT.rglob("*")):
        rel = path.relative_to(ROOT)
        if any(part in EXCLUDED_PARTS for part in rel.parts) or path.name in EXCLUDED_NAMES or path.name.endswith("_RESULTS.json"):
            continue
        if path.is_symlink():
            raise RuntimeError(f"symlink forbidden: {rel.as_posix()}")
        if path.is_file() and path.suffix not in {".pyc", ".pyo"}:
            yield rel, path.read_bytes()


def manifest_bytes(files):
    return "".join(f"{hashlib.sha256(data).hexdigest()}  {rel.as_posix()}\n" for rel, data in files).encode()


def build(output: Path, *, write_manifest: bool):
    files = list(release_files())
    manifest = manifest_bytes(files)
    if write_manifest:
        (ROOT / "MANIFEST.sha256").write_bytes(manifest)
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9, strict_timestamps=True) as archive:
        for rel, data in files + [(Path("MANIFEST.sha256"), manifest)]:
            info = zipfile.ZipInfo(f"{PACKAGE_ROOT}/{rel.as_posix()}", date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o100644 & 0xFFFF) << 16
            info.create_system = 3
            archive.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    return {"output": str(output), "sha256": digest, "files": len(files) + 1, "package_root": PACKAGE_ROOT}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "dist" / "ZORAN_COHERENCE_SKILL_v22.3.0_CANDIDATE.zip")
    parser.add_argument("--write-manifest", action="store_true")
    args = parser.parse_args()
    print(json.dumps(build(args.output.resolve(), write_manifest=args.write_manifest), sort_keys=True))


if __name__ == "__main__":
    main()
