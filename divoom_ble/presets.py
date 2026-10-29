"""Ready-made animated screens.

Each preset uses a small palette and changes few pixels per frame, because the device
draws pixel diffs quickly (drawing pad) but full many-colour images slowly.
"""
import math
import random
import time as _time

from .fonts import BIG, SMALL, render_text
from .scenes import SIZE, Frame, Scene

BLACK = (0, 0, 0)


def _blank(c=BLACK) -> Frame:
    return [c] * (SIZE * SIZE)


def _set(f: Frame, x: int, y: int, c) -> None:
    if 0 <= x < SIZE and 0 <= y < SIZE:
        f[y * SIZE + x] = c


def _sprite(f: Frame, rows: list[str], x0: int, y0: int, colours: dict) -> None:
    for y, row in enumerate(rows):
        for x, ch in enumerate(row):
            if ch in colours:
                _set(f, x0 + x, y0 + y, colours[ch])


def _text(f: Frame, text: str, x0: int, y0: int, c, font=SMALL) -> None:
    for y, row in enumerate(render_text(text, font)):
        for x, on in enumerate(row):
            if on:
                _set(f, x0 + x, y0 + y, c)


# ---- sprites ----------------------------------------------------------------
HEART_BIG = ["  ##   ##  ", " #### #### ", "###########", "###########", "###########",
             " ######### ", "  #######  ", "   #####   ", "    ###    ", "     #     "]
HEART_SMALL = [" ## ## ", "#######", "#######", " ##### ", "  ###  ", "   #   "]
PAC_OPEN = ["  ####  ", " ###### ", "######  ", "#####   ", "#####   ", "######  ", " ###### ", "  ####  "]
PAC_SHUT = ["  ####  ", " ###### ", "########", "########", "########", "########", " ###### ", "  ####  "]
GHOST = ["  ####  ", " ###### ", "##WW##WW", "##WB##WB", "########", "########", "########", "# ## ## #"[:8]]
ARROW = ["      ##        ", "     ###        ", "    ####        ", "   ##########   ",
         "  ###########   ", " ############   ", "  ###########   ", "   ##########   ",
         "    ####        ", "     ###        ", "      ##        "]


class PresetScene(Scene):
    kind = "preset"

    def __init__(self, name: str):
        if name not in PRESETS:
            raise ValueError(f"unknown preset {name!r}; try one of {', '.join(PRESETS)}")
        self.name = name
        self.title, self.interval, loop, self._fn = PRESETS[name]
        self.live = loop is None
        self.loop_seconds = loop
        self.state: dict = {"rng": random.Random(7)}

    def render(self, t):
        return self._fn(t, self.state)

    def describe(self):
        return {"kind": self.kind, "name": self.name, "title": self.title}


# ---- preset functions: (t seconds, state) -> frame ---------------------------
def heartbeat(t, st):
    f = _blank()
    beat = t % 1.1
    big = beat < 0.12 or 0.28 < beat < 0.40          # lub-dub
    if big:
        _sprite(f, HEART_BIG, 2, 3, {"#": (235, 20, 60)})
    else:
        _sprite(f, HEART_SMALL, 4, 5, {"#": (170, 10, 40)})
    return f


def matrix(t, st):
    rng = st["rng"]
    drops = st.setdefault("drops", [[x, rng.randint(-16, 0), 7 * rng.choice((1, 2, 3))] for x in range(0, 16)])
    f = _blank()
    for d in drops:
        x, y0, speed = d
        head = round(y0 + t * speed) % 28 - 6
        for k, c in enumerate(((180, 255, 180), (0, 200, 60), (0, 110, 30))):
            _set(f, x, head - k, c)
    return f


def starfield(t, st):
    rng = st["rng"]
    stars = st.setdefault("stars", [(rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(0, 1)) for _ in range(28)])
    f = _blank((0, 0, 12))
    for sx, sy, phase in stars:
        z = 1.0 - ((t * 0.35 + phase) % 1.0) + 0.02
        x, y = 7.5 + sx / z * 4, 7.5 + sy / z * 4
        c = (255, 255, 255) if z < 0.35 else (120, 130, 160)
        _set(f, int(x), int(y), c)
    return f


def pacman(t, st):
    f = _blank()
    span = 40
    pos = round(t * 10) % span - 10
    for x in range(0, 16, 3):                     # dots not yet eaten
        if x > pos + 6:
            _set(f, x, 7, (255, 200, 160))
    mouth = PAC_OPEN if round(t * 5) % 2 else PAC_SHUT
    _sprite(f, mouth, pos, 4, {"#": (255, 220, 0)})
    _sprite(f, GHOST, pos - 11, 4, {"#": (255, 60, 60), "W": (255, 255, 255), "B": (30, 60, 255)})
    return f


def bounce(t, st):
    f = _blank()
    trail = []
    for k in range(4):
        tt = t - k * 0.05
        x = abs((tt * 6.5) % 26 - 13) + 1
        y = 14 - abs(math.sin(tt * math.pi * 3 / 4)) * 12
        trail.append((int(round(x)), int(round(y))))
    for k, (x, y) in reversed(list(enumerate(trail))):
        c = [(0, 200, 255), (0, 120, 170), (0, 70, 110), (0, 35, 60)][k]
        _set(f, x, y, c)
        if k == 0:
            _set(f, x + 1, y, c); _set(f, x, y + 1, c); _set(f, x + 1, y + 1, c)
    for x in range(16):
        _set(f, x, 15, (60, 60, 60))
    return f


def smiley(t, st):
    f = _blank()
    yellow, dark = (255, 205, 0), (40, 20, 0)
    for y in range(16):
        for x in range(16):
            if (x - 7.5) ** 2 + (y - 7.5) ** 2 <= 56:
                f[y * 16 + x] = yellow
    blink = (t % 3.0) > 2.75
    wink = (t % 9.0) > 8.0
    for x in (5, 10):
        if blink or (wink and x == 10):
            _set(f, x - 1, 6, dark); _set(f, x, 6, dark)
        else:
            _set(f, x - 1, 5, dark); _set(f, x - 1, 6, dark); _set(f, x, 5, dark); _set(f, x, 6, dark)
    for x, y in ((4, 9), (5, 10), (6, 11), (7, 11), (8, 11), (9, 11), (10, 10), (11, 9)):
        _set(f, x, y, dark)
    return f


def rainbow_hi(t, st):
    f = _blank()
    hue = (t * 0.25) % 1.0
    h6 = hue * 6
    i, frac = int(h6), h6 - int(h6)
    r, g, b = [(1, frac, 0), (1 - frac, 1, 0), (0, 1, frac), (0, 1 - frac, 1), (frac, 0, 1), (1, 0, 1 - frac)][i % 6]
    colour = (int(r * 255) // 16 * 16, int(g * 255) // 16 * 16, int(b * 255) // 16 * 16)   # fewer distinct colours
    _text(f, "HI!", 2, 4, colour, BIG)
    return f


def life(t, st):
    rng = st["rng"]
    gen = int(t * 6)
    if "grid" not in st or st.get("stale", 0) > 25 or gen < st.get("gen", 0):
        st.update(grid={(x, y) for x in range(16) for y in range(16) if rng.random() < 0.32},
                  gen=gen, stale=0, history=[])
    while st["gen"] < gen:
        g = st["grid"]
        counts = {}
        for x, y in g:
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    if dx or dy:
                        k = ((x + dx) % 16, (y + dy) % 16)
                        counts[k] = counts.get(k, 0) + 1
        new = {k for k, n in counts.items() if n == 3 or (n == 2 and k in g)}
        sig = frozenset(new)
        st["stale"] = st["stale"] + 1 if sig in st["history"] else 0
        st["history"] = (st["history"] + [sig])[-12:]
        st["grid"], st["gen"] = new, st["gen"] + 1
    f = _blank()
    for x, y in st["grid"]:
        f[y * 16 + x] = (120, 255, 90)
    return f


def clock(t, st):
    f = _blank()
    now = _time.localtime()
    _text(f, f"{now.tm_hour:02d}", 4, 2, (255, 255, 255))
    _text(f, f"{now.tm_min:02d}", 4, 9, (242, 194, 48))
    for k in range(now.tm_sec // 4 + 1):           # seconds ticking down the right edge
        _set(f, 15, k, (47, 91, 234))
    return f


def _signal(direction: int):
    def fn(t, st):
        f = _blank()
        if (t % 0.9) < 0.5:
            rows = ARROW if direction < 0 else [r[::-1] for r in ARROW]
            _sprite(f, rows, 0, 2, {"#": (255, 150, 0)})
        return f
    return fn


def eyes(t, st):
    f = _blank()
    white, pupil = (240, 240, 240), (20, 90, 255)
    look = [(0, 0), (-1, 0), (-1, 1), (1, 0), (1, -1), (0, 0)][int(t / 1.2) % 6]
    blink = (t % 3.6) > 3.45
    for cx in (4, 11):
        if blink:
            for x in range(cx - 3, cx + 3):
                _set(f, x, 8, white)
            continue
        for y in range(4, 13):
            for x in range(cx - 3, cx + 3):
                if ((x + .5 - cx) / 3.2) ** 2 + ((y - 8) / 4.6) ** 2 <= 1:
                    _set(f, x, y, white)
        px, py = cx - 1 + look[0], 7 + look[1]
        for dx in (0, 1):
            for dy in (0, 1):
                _set(f, px + dx, py + dy, pupil)
    return f


# name: (button title, seconds per frame, loop length in seconds or None for live, function)
PRESETS = {
    "heartbeat": ("Heartbeat", 0.05, 1.1, heartbeat),
    "smiley": ("Winking smiley", 0.05, 9.0, smiley),
    "eyes": ("Watching eyes", 0.1, 7.2, eyes),
    "pacman": ("Pac-Man chase", 0.1, 4.0, pacman),
    "matrix": ("Matrix rain", 2 / 21, 4.0, matrix),
    "starfield": ("Starfield", 0.08, 1 / 0.35, starfield),
    "bounce": ("Bouncing ball", 0.1, 4.0, bounce),
    "life": ("Game of Life", 0.16, 9.6, life),
    "rainbow": ("Rainbow HI!", 0.1, 4.0, rainbow_hi),
    "clock": ("Big clock", 1.0, None, clock),
    "left": ("Turning left", 0.05, 0.9, _signal(-1)),
    "right": ("Turning right", 0.05, 0.9, _signal(1)),
}
