import json
import os
import subprocess
import sys
from pathlib import Path

HOOK = Path(__file__).with_name("statusline_hook.py")


def run_hook(payload: dict, usage_file: Path) -> str:
    env = {**os.environ, "DIVOOM_USAGE_FILE": str(usage_file)}
    out = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), capture_output=True,
                         text=True, env=env, check=True)
    return out.stdout.strip()


def test_hook_saves_rate_limits_and_prints_a_status_line(tmp_path):
    usage = tmp_path / "usage.json"
    line = run_hook({"model": {"display_name": "Opus"},
                     "rate_limits": {"five_hour": {"used_percentage": 23.5, "resets_at": 1738425600},
                                     "seven_day": {"used_percentage": 41.2, "resets_at": 1738857600}}}, usage)
    assert line == "Opus | 5h 24% | 7d 41%"
    data = json.loads(usage.read_text())
    assert data["five_hour"] == {"percent": 23.5, "resets_at": 1738425600}
    assert data["seven_day"]["percent"] == 41.2 and data["fetched_at"] > 0


def test_hook_leaves_the_file_alone_without_rate_limits(tmp_path):
    usage = tmp_path / "usage.json"
    assert run_hook({"model": {"display_name": "Opus"}}, usage) == "Opus"
    assert not usage.exists()
