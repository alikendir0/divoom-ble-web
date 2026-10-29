"""What can be on the screen. Each scene renders a 256-pixel frame for a given time."""
import io
import math

from PIL import Image, ImageSequence

from .fonts import FONTS, render_text
from .protocol import Pixel

SIZE = 16
Frame = list[Pixel]


def parse_colour(value, default: Pixel = (255, 255, 255)) -> Pixel:
    """Accept '#rrggbb', 'rrggbb', '#rgb', [r, g, b] or (r, g, b)."""
    if value is None or value == "":
        return default
    if isinstance(value, (list, tuple)) and len(value) == 3:
        return tuple(max(0, min(255, int(c))) for c in value)
    s = str(value).strip().lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    if len(s) != 6:
        raise ValueError(f"bad colour {value!r}")
    return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))


def to_hex(frame: Frame) -> list[str]:
    return ["%02x%02x%02x" % c for c in frame]


def _blit(frame: Frame, rows: list[list[bool]], x0: int, y0: int, colour: Pixel) -> None:
    for y, row in enumerate(rows):
        yy = y0 + y
        if not 0 <= yy < SIZE:
            continue
        for x, on in enumerate(row):
            xx = x0 + x
            if on and 0 <= xx < SIZE:
                frame[yy * SIZE + xx] = colour


class Scene:
    kind = "scene"
    interval = 0.0          # seconds between frames; 0 = a still picture
    loop_seconds = None     # length of one seamless loop, uploaded to the device as an animation
    live = False            # True: content depends on the wall clock, re-sent as stills

    def render(self, t: float) -> Frame:
        raise NotImplementedError

    def loop(self) -> list[tuple[Frame, int]] | None:
        """Frames [(frame, ms)] for one loop, or None if this scene is not an animation."""
        if not self.interval or not self.loop_seconds or self.live:
            return None
        n = max(1, round(self.loop_seconds / self.interval))
        ms = round(self.interval * 1000)
        return [(self.render(k * self.interval), ms) for k in range(n)]

    def describe(self) -> dict:
        return {"kind": self.kind}


class PixelsScene(Scene):
    kind = "pixels"

    def __init__(self, pixels):
        if len(pixels) != SIZE * SIZE:
            raise ValueError(f"need {SIZE * SIZE} pixels, got {len(pixels)}")
        self.frame = [parse_colour(c) for c in pixels]

    def render(self, t):
        return list(self.frame)


class _ScrollLine:
    """One line of text: centred if it fits, otherwise scrolls right-to-left."""

    def __init__(self, text: str, font: str, speed: float):
        self.rows = render_text(text, FONTS[font])
        self.width = len(self.rows[0]) if self.rows else 0
        self.height = len(self.rows)
        self.speed = max(1.0, float(round(speed)))
        self.scrolls = self.width > SIZE
        self.period = self.width + SIZE   # pixels per loop; may be stretched to sync lines

    def x(self, t: float) -> int:
        if not self.scrolls:
            return max(0, (SIZE - self.width) // 2)
        # starts left-aligned, leaves on the left, re-enters from the right
        return SIZE - (round(t * self.speed) + SIZE) % self.period


def _sync_lines(lines: list[_ScrollLine]) -> float | None:
    """Give all scrolling lines the same speed and period; return the loop length in seconds."""
    moving = [l for l in lines if l.scrolls]
    if not moving:
        return None
    speed, period = moving[0].speed, max(l.period for l in moving)
    for l in moving:
        l.speed, l.period = speed, period
    return period / speed


class TextScene(Scene):
    kind = "text"

    def __init__(self, text: str, color="#ffffff", bg="#000000", font: str = "big",
                 speed: float = 14.0):
        if font not in FONTS:
            raise ValueError("font must be 'big' or 'small'")
        self.params = {"text": text, "color": color, "bg": bg, "font": font, "speed": speed}
        self.fg, self.bg = parse_colour(color), parse_colour(bg, (0, 0, 0))
        lines = text.split("\n")[: 1 if font == "big" else 2]
        self.lines = [_ScrollLine(line, font, speed) for line in lines]
        self.loop_seconds = _sync_lines(self.lines)
        self.interval = 1.0 / self.lines[0].speed if self.loop_seconds else 0.0

    def render(self, t):
        frame = [self.bg] * (SIZE * SIZE)
        total = sum(l.height for l in self.lines) + 2 * (len(self.lines) - 1)
        y = (SIZE - total) // 2
        for line in self.lines:
            _blit(frame, line.rows, line.x(t), y, self.fg)
            y += line.height + 2
        return frame

    def describe(self):
        return {"kind": self.kind, **self.params}


class ValueScene(Scene):
    """A small data widget: label on top, big value in the middle, optional bar at the bottom.

    Always a still picture, so new values swap in instantly with no loading symbol.
    Text that does not fit is cut off instead of scrolling.
    """
    kind = "value"

    def __init__(self, value, label: str = "", color="#ffffff", label_color="#888888",
                 bg="#000000", bar: float | None = None, bar_color="#00c8ff"):
        self.params = {"value": value, "label": label, "color": color, "label_color": label_color,
                       "bg": bg, "bar": bar, "bar_color": bar_color}
        self.fg, self.lc, self.bg = parse_colour(color), parse_colour(label_color), parse_colour(bg, (0, 0, 0))
        self.bc = parse_colour(bar_color)
        self.bar = None if bar is None else max(0.0, min(1.0, float(bar)))
        text = str(value)
        big = render_text(text, FONTS["big"])
        self.value = _ScrollLine(text, "big" if len(big[0]) <= SIZE else "small", 10)
        self.label = _ScrollLine(label, "small", 10) if label else None
        for line in (self.value, self.label):
            if line and line.scrolls:
                line.scrolls = False          # left-aligned and cut off at the edge

    def render(self, t):
        frame = [self.bg] * (SIZE * SIZE)
        if self.label:
            _blit(frame, self.label.rows, self.label.x(t), 0, self.lc)
            vy = 7 if self.value.height == 7 else 8
        else:
            vy = (SIZE - self.value.height) // 2 - (1 if self.bar is not None else 0)
        _blit(frame, self.value.rows, self.value.x(t), vy, self.fg)
        if self.bar is not None:
            lit = round(self.bar * SIZE)
            for x in range(SIZE):
                frame[15 * SIZE + x] = self.bc if x < lit else tuple(c // 6 for c in self.bc)
        return frame

    def describe(self):
        return {"kind": self.kind, **self.params}


class ImageScene(Scene):
    """A picture or animated GIF, scaled to 16x16."""
    kind = "image"

    def __init__(self, data: bytes, fit: str = "cover", name: str = "image"):
        self.name, self.fit = name, fit
        img = Image.open(io.BytesIO(data))
        self.frames: list[Frame] = []
        self.durations: list[float] = []
        for frame in ImageSequence.Iterator(img):
            self.frames.append(self._convert(frame.convert("RGBA")))
            self.durations.append(max(0.02, frame.info.get("duration", 100) / 1000))
            if len(self.frames) >= 300:
                break
        self.total = sum(self.durations)
        self.interval = 0.02 if len(self.frames) > 1 else 0.0
        self.loop_seconds = self.total if len(self.frames) > 1 else None

    def loop(self):
        if len(self.frames) < 2:
            return None
        return [(list(f), round(d * 1000)) for f, d in zip(self.frames, self.durations)]

    def _convert(self, im: Image.Image) -> Frame:
        if self.fit == "cover":
            s = min(im.width, im.height)
            im = im.crop(((im.width - s) // 2, (im.height - s) // 2,
                          (im.width + s) // 2, (im.height + s) // 2))
        else:
            s = max(im.width, im.height)
            canvas = Image.new("RGBA", (s, s), (0, 0, 0, 255))
            canvas.paste(im, ((s - im.width) // 2, (s - im.height) // 2))
            im = canvas
        resample = Image.Resampling.NEAREST if max(im.size) <= 64 else Image.Resampling.BOX
        im = im.resize((SIZE, SIZE), resample)
        bg = Image.new("RGBA", im.size, (0, 0, 0, 255))
        im = Image.alpha_composite(bg, im).convert("RGB")
        get = getattr(im, "get_flattened_data", None) or im.getdata
        return list(get())

    def render(self, t):
        if len(self.frames) == 1:
            return list(self.frames[0])
        t = math.fmod(t, self.total)
        for frame, d in zip(self.frames, self.durations):
            if t < d:
                return list(frame)
            t -= d
        return list(self.frames[-1])

    def describe(self):
        return {"kind": self.kind, "name": self.name, "frames": len(self.frames), "fit": self.fit}
