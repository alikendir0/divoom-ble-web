"""Claude Code status line command that saves your usage limits for the Divoom screen.

Claude Code pipes a JSON payload to its status line command on stdin. For Pro and Max
subscribers it includes `rate_limits.five_hour` and `rate_limits.seven_day`, each with
`used_percentage` and `resets_at` (https://code.claude.com/docs/en/statusline).
This script copies those into a small JSON file and prints a one-line status line.

Use it as your status line in ~/.claude/settings.json:

    "statusLine": {"type": "command", "command": "python /path/to/statusline_hook.py"}

or call it from your existing status line script with the same stdin.
"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

USAGE_FILE = Path(os.environ.get("DIVOOM_USAGE_FILE", Path.home() / ".claude" / "divoom-usage.json"))
MIN_WRITE_INTERVAL = 60      # rewrite at most once a minute unless the numbers change


def window(rate_limits: dict, key: str) -> dict | None:
    w = rate_limits.get(key) or {}
    if isinstance(w.get("used_percentage"), (int, float)):
        return {"percent": w["used_percentage"], "resets_at": w.get("resets_at")}
    return None


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        payload = {}
    limits = payload.get("rate_limits") or {}
    five, week = window(limits, "five_hour"), window(limits, "seven_day")

    if five or week:
        try:
            old = json.loads(USAGE_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            old = {}
        changed = (old.get("five_hour"), old.get("seven_day")) != (five, week)
        if changed or time.time() - old.get("fetched_at", 0) > MIN_WRITE_INTERVAL:
            USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
            data = json.dumps({"fetched_at": int(time.time()), "five_hour": five, "seven_day": week})
            with tempfile.NamedTemporaryFile("w", dir=USAGE_FILE.parent, delete=False, encoding="utf-8") as tmp:
                tmp.write(data)
            os.replace(tmp.name, USAGE_FILE)            # atomic: the screen never reads half a file

    parts = []
    if five:
        parts.append(f"5h {five['percent']:.0f}%")
    if week:
        parts.append(f"7d {week['percent']:.0f}%")
    model = (payload.get("model") or {}).get("display_name")
    print(" | ".join(([model] if model else []) + parts))


if __name__ == "__main__":
    main()
