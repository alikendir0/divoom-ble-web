"""Clawd and a Claude usage screen for 16x16 Divoom displays.

Clawd is the Claude Code mascot (Anthropic). This is a fan-made example, not affiliated
with Anthropic or Divoom.

The screen reads a small JSON file:
    {"fetched_at": <epoch s>,
     "five_hour": {"percent": <used %>, "resets_at": <epoch s>},
     "seven_day": {"percent": <used %>, "resets_at": <epoch s>}}
statusline_hook.py writes it from Claude Code's status line.
"""
import json
import time
from pathlib import Path

from divoom_ble.scenes import SIZE, Frame, Scene

DEFAULT_USAGE_FILE = Path.home() / ".claude" / "divoom-usage.json"

# Claude's brand coral (217, 119, 87) looks washed out on LEDs: its green and blue
# channels light up too, so the panel shows a pale peach. This saturated orange reads right.
CLAUDE_ORANGE = (255, 80, 20)
TRACK = (45, 12, 3)
HIGH = (255, 30, 30)                 # a bar above 85 % used
EYE = (0, 0, 0)

# Big Clawd, 14 wide. '#' body, 'K' eye.
_BODY = [
    "...##########...",
    "...##########...",
    "...##K####K##...",
    "...##K####K##...",
    ".##############.",
    ".##############.",
    "...##########...",
    "...##########...",
]
_LEGS = (4, 6, 9, 11)


def _put(f: Frame, x: int, y: int, c) -> None:
    if 0 <= x < SIZE and 0 <= y < SIZE:
        f[y * SIZE + x] = c


def _clawd(f: Frame, t: float, top: int, ground: int, tired: bool = False, look: int = 0,
           excited: bool = False) -> None:
    """Draw Clawd with his body starting at row `top` and legs reaching down to row `ground`.

    `tired` makes him squint (half-closed eyes) and stop waving; `look` (-1, 0, 1) shifts
    his eyes to glance left or right; `excited` makes him wave non-stop.
    """
    # Every move lands on a 0.25 s beat.
    waving = excited or (1.0 <= (t % 4.0) < 2.5 and not tired)
    arm_up = waving and (t % 0.5) < 0.25
    blink = tired or 3.25 <= (t % 4.0) < 3.5
    for y, row in enumerate(_BODY):
        for x, ch in enumerate(row):
            if ch == ".":
                continue
            if y in (4, 5) and x >= 13 and arm_up:
                continue                          # right arm moves up instead
            _put(f, x, top + y, CLAUDE_ORANGE)
    for y, row in enumerate(_BODY):
        for x, ch in enumerate(row):
            if ch == "K" and not (blink and y == 2):
                _put(f, x + look, top + y, EYE)
    if arm_up:
        for y in (top + 2, top + 3):
            for x in (13, 14):
                _put(f, x, y, CLAUDE_ORANGE)
    for x in _LEGS:
        for y in range(top + len(_BODY), ground + 1):
            _put(f, x, y, CLAUDE_ORANGE)


def draw_clawd(t: float) -> Frame:
    """One frame of Clawd: bobbing, blinking, waving his right arm now and then."""
    f = [(0, 0, 0)] * (SIZE * SIZE)
    up = 1 if (t % 1.0) < 0.5 else 0             # gentle bob; legs stretch while he is up
    _clawd(f, t, top=4 - up, ground=13)
    return f


def read_usage(path: Path = DEFAULT_USAGE_FILE) -> dict:
    """Return used percentages, reset times (epoch seconds) and cache age; values may be None."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"five_hour_used": None, "seven_day_used": None, "five_hour_resets_at": None,
                "seven_day_resets_at": None, "fetched_at": None, "age_seconds": None}
    now = time.time()

    def used(key):
        entry = data.get(key) or {}
        pct = entry.get("percent")
        if not isinstance(pct, (int, float)):
            return None
        if isinstance(entry.get("resets_at"), (int, float)) and entry["resets_at"] <= now:
            return 0                              # the window has reset since the cache was written
        return max(0, min(100, round(pct)))

    fetched = data.get("fetched_at")
    return {"five_hour_used": used("five_hour"), "seven_day_used": used("seven_day"),
            "five_hour_resets_at": (data.get("five_hour") or {}).get("resets_at"),
            "seven_day_resets_at": (data.get("seven_day") or {}).get("resets_at"),
            "fetched_at": fetched if isinstance(fetched, (int, float)) else None,
            "age_seconds": round(now - fetched) if isinstance(fetched, (int, float)) else None}


class ClawdScene(Scene):
    kind = "preset"
    interval = 0.1
    loop_seconds = 4.0

    def render(self, t):
        return draw_clawd(t)

    def describe(self):
        return {"kind": self.kind, "name": "clawd", "title": "Clawd"}


# Under Clawd: two 1-pixel bars filling from the left with the percentage used. Each is as
# wide as its sections divide evenly, so every hour / day gets the same number of pixels:
#   5-hour limit: row 11, x1-15 (15 px = 5 hours x 3 px); tick dots in row 12
#   weekly limit: row 14, x1-14 (14 px = 7 days x 2 px) plus an end cap at x15 so both
#                 bars line up; the cap only lights when the week is fully used.
#                 Tick dots in row 15.
# A tick dot sits under the first pixel of every section after the first.
# A faint grey pixel on each bar marks how far into the window the clock is: when the orange
# runs ahead of it, usage is outpacing time.
BAR_X0 = 1
FIVE_ROW, FIVE_WIDTH, FIVE_SECTIONS = 11, 15, 5
WEEK_ROW, WEEK_WIDTH, WEEK_SECTIONS = 14, 14, 7
FIVE_TICKS = tuple(BAR_X0 + k * FIVE_WIDTH // FIVE_SECTIONS for k in range(1, FIVE_SECTIONS))   # 4, 7, 10, 13
WEEK_TICKS = tuple(BAR_X0 + k * WEEK_WIDTH // WEEK_SECTIONS for k in range(1, WEEK_SECTIONS))   # 3, 5, ..., 13
FIVE_WINDOW, WEEK_WINDOW = 5 * 3600, 7 * 24 * 3600
WEEK_CAP_X = BAR_X0 + WEEK_WIDTH                                                       # 15

# Freshness, shown by Clawd instead of text:
#   new numbers arrive -> he celebrates for CELEBRATE_SECONDS (waves, all stars on)
#   nothing new for STALE_AFTER -> he falls asleep (eyes shut, still, a "z" floats up)
CELEBRATE_SECONDS = 2.0
STALE_AFTER = 10 * 60
SLEEP_Z = ((13, 2), (14, 1), (15, 0))     # the z drifts up and right, one step per beat
TICK = TRACK                         # same dim orange as the empty bar: fewer colours
MARKER = (70, 70, 70)              # faint grey: where the clock is in the window
# Single-pixel stars twinkling in the empty corners around Clawd: (x, y, phase offset).
# Placed so they never touch him, even when he bobs up or raises his arm.
STARS = ((1, 1, 0.0), (15, 0, 1.5), (0, 8, 1.0), (15, 9, 0.5))   # offsets on the 0.5 s beat
STAR_LEVELS = (MARKER, (0, 0, 0))   # faint grey twinkle; reuses the marker colour


def elapsed_fraction(resets_at, window: int, now: float | None = None) -> float | None:
    """How far through its window a limit is (0 = just reset, 1 = about to reset)."""
    if not isinstance(resets_at, (int, float)):
        return None
    now = time.time() if now is None else now
    return max(0.0, min(1.0, 1 - (resets_at - now) / window))


class ClaudeUsageScene(Scene):
    """Big Clawd with twinkling stars; under him the 5-hour and weekly bars.

    Animated with whole-screen still images (0x44): the device swaps each one in at once,
    so there is no upload (no loading symbol) and no drawing-pad flicker or ghosting.
    Every change lands on a 0.25 s beat, and the screen uses only four colours (black,
    orange, dim orange, faint grey) so each image is small and quick to send.
    """
    kind = "claude"
    interval = 0.25
    live = True

    def __init__(self, usage: dict | None = None, clock=time.time):
        self.usage = usage if usage is not None else read_usage()
        self.clock = clock
        self.celebrate_until = 0.0

    def update(self, usage: dict) -> bool:
        """Take newer numbers from the status line cache; returns True if anything changed.

        Clawd celebrates every fresh fetch, even when the numbers are the same, so a lively
        Clawd always means the data is current.
        """
        if usage == self.usage:
            return False
        if usage.get("five_hour_used") is None and usage.get("seven_day_used") is None and (
                self.usage.get("five_hour_used") is not None or self.usage.get("seven_day_used") is not None):
            return False      # a failed fetch (e.g. expired login) wrote empty numbers: keep the last good ones
        fresh = usage.get("fetched_at") != self.usage.get("fetched_at")
        self.usage = usage
        if fresh and usage.get("fetched_at") is not None:
            self.celebrate_until = self.clock() + CELEBRATE_SECONDS
        return True

    def asleep(self, now: float) -> bool:
        fetched = self.usage.get("fetched_at")
        return fetched is None or now - fetched > STALE_AFTER

    @staticmethod
    def _bar(f: Frame, row: int, width: int, ticks, used, elapsed, t) -> None:
        lit = 0 if used is None else round(used / 100 * width)
        high = used is not None and used > 85
        dim = high and (t % 1.0) >= 0.75         # pulse when nearly used up (on the 0.25 s beat)
        on = HIGH if high else CLAUDE_ORANGE
        for i in range(width):
            _put(f, BAR_X0 + i, row, on if (i < lit and not dim) else TRACK)
        if elapsed is not None:
            _put(f, BAR_X0 + min(width - 1, int(elapsed * width)), row, MARKER)
        for x in ticks:
            _put(f, x, row + 1, TICK)

    @staticmethod
    def _stars(f: Frame, t: float, skip_right: bool = False) -> None:
        for x, y, offset in STARS:
            if skip_right and x > 8:
                continue                           # that corner belongs to the sleeping "z"
            level = STAR_LEVELS[int((t + offset) / 0.5) % len(STAR_LEVELS)]
            if level != (0, 0, 0):
                _put(f, x, y, level)

    def render(self, t):
        f = [(0, 0, 0)] * (SIZE * SIZE)
        now = self.clock()
        five, week = self.usage["five_hour_used"], self.usage.get("seven_day_used")
        celebrating = now < self.celebrate_until
        sleeping = not celebrating and self.asleep(now)
        tired = sleeping or (five is not None and five > 85)
        up = 1 if (t % 1.0) < 0.5 and not sleeping else 0     # bob; a sleeping Clawd keeps still
        cycle = t % 8.0
        look = -1 if 4.5 <= cycle < 5.5 else (1 if 5.5 <= cycle < 6.5 else 0)   # glance around
        _clawd(f, t, top=1 - up, ground=9, tired=tired, look=0 if tired else look,
               excited=celebrating)
        if celebrating:
            for x, y, _ in STARS:
                _put(f, x, y, MARKER)              # every star on at once
        elif sleeping:
            self._stars(f, t, skip_right=True)
            x, y = SLEEP_Z[int(t / 0.5) % len(SLEEP_Z)]
            _put(f, x, y, MARKER)
        else:
            self._stars(f, t)
        self._bar(f, FIVE_ROW, FIVE_WIDTH, FIVE_TICKS, five,
                  elapsed_fraction(self.usage.get("five_hour_resets_at"), FIVE_WINDOW, now), t)
        self._bar(f, WEEK_ROW, WEEK_WIDTH, WEEK_TICKS, week,
                  elapsed_fraction(self.usage.get("seven_day_resets_at"), WEEK_WINDOW, now), t)
        full_week = week is not None and week >= 100
        _put(f, WEEK_CAP_X, WEEK_ROW, f[WEEK_ROW * SIZE + WEEK_CAP_X - 1] if full_week else TRACK)
        return f

    def describe(self):
        return {"kind": self.kind, **self.usage}
