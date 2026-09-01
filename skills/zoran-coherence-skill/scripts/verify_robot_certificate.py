#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from robot_certificate import verify_release_certificate  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("certificate", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--mission-sha256", required=True)
    args = parser.parse_args()
    envelope = json.loads(args.certificate.read_text(encoding="utf-8"))
    candidate_sha = __import__("hashlib").sha256(args.candidate.read_bytes()).hexdigest()
    payload, certificate_sha = verify_release_certificate(
        envelope,
        mission_sha256=args.mission_sha256,
        candidate_sha256=candidate_sha,
    )
    print(json.dumps({"verdict": payload["verdict"], "candidate_sha256": candidate_sha, "certificate_sha256": certificate_sha}, sort_keys=True))


if __name__ == "__main__":
    main()
