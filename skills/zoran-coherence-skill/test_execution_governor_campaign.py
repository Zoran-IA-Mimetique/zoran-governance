from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_execution_governor_campaign_is_deterministic(tmp_path: Path):
    root = Path(__file__).resolve().parent
    script = root / "scripts" / "run_execution_governor_campaign.py"
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    for output in (first, second):
        subprocess.run(
            [sys.executable, str(script), "--cases-per-category", "2", "--output", str(output)],
            cwd=root,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
    assert first.read_bytes() == second.read_bytes()
    result = json.loads(first.read_text(encoding="utf-8"))
    assert result["verdict"] == "PASS"
    assert result["total_cases"] == 24
    assert result["failed"] == 0
