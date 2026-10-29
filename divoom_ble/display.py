"""Gets content onto the device without tearing or flicker.

Every screen change is applied by the device in one step:
  * still frames (drawing, widgets, pictures) go out as one 0x44 image;
  * moving content is uploaded once as a native animation (0x8B, "2020" protocol)
    which the device then plays by itself, perfectly smoothly.
Work is "latest wins": a newer frame or animation cancels whatever is still pending.
"""
import asyncio
import logging
import time

from . import protocol as p
from .device import DivoomDevice

log = logging.getLogger(__name__)

CMD_ANIMATION = 0x8B
CHUNK = 256
WINDOW = 4                       # packets in flight during an upload
MAX_ANIMATION_BYTES = 48_000     # the app re-encodes above ~50 KB, so stay below that

Frame = list[p.Pixel]


def merge_repeats(frames: list[tuple[Frame, int]]) -> list[tuple[Frame, int]]:
    """Join consecutive identical frames by adding their durations (max 65535 ms each)."""
    out: list[tuple[Frame, int]] = []
    for frame, ms in frames:
        if out and out[-1][0] == frame and out[-1][1] + ms <= 0xFFFF:
            out[-1] = (frame, out[-1][1] + ms)
        else:
            out.append((frame, ms))
    return out


def encode_animation(frames: list[tuple[Frame, int]]) -> bytes:
    """Concatenate encoded frames, halving the frame count until it fits the size budget."""
    frames = merge_repeats(frames)
    while True:
        data = b"".join(p.encode_frame(f, max(1, min(ms, 0xFFFF))) for f, ms in frames)
        if len(data) <= MAX_ANIMATION_BYTES or len(frames) < 2:
            return data
        frames = merge_repeats([(frames[i][0], frames[i][1] + (frames[i + 1][1] if i + 1 < len(frames) else 0))
                                for i in range(0, len(frames), 2)])


class Display:
    def __init__(self, device: DivoomDevice):
        self.device = device
        self._job: tuple[str, object] | None = None     # ("frame", Frame) or ("animation", bytes)
        self._shown_job: tuple[str, object] | None = None
        self._changed = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._update_times: list[float] = []
        self.upload_progress: float | None = None        # 0..1 while an animation is uploading
        self.on_progress = None                          # callback(progress | None)

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    # ---- requests ---------------------------------------------------------
    def show(self, frame: Frame) -> None:
        """Show one still frame."""
        if len(frame) != 256:
            raise ValueError("frame must have 256 pixels")
        self._submit(("frame", [tuple(c) for c in frame]))

    def play(self, frames: list[tuple[Frame, int]], settle: float = 0.0) -> None:
        """Upload frames [(frame, duration_ms), …] as a looping animation the device plays itself.

        The first frame is shown at once as a still (no loading symbol). With `settle`, the
        upload, which shows the device's loading symbol, waits until no newer content has
        arrived for that many seconds, e.g. while someone is still typing.
        """
        self._submit(("animation", encode_animation(frames), frames[0][0], settle))

    def release(self) -> None:
        """Stop driving the screen (a built-in channel took over)."""
        self._job, self._shown_job = None, None

    def invalidate(self) -> None:
        """Send the current content again (after a reconnect or someone else changed the screen)."""
        self._shown_job = None
        if self._job is not None:
            self._changed.set()

    def _submit(self, job) -> None:
        self._job = job
        self._changed.set()

    @property
    def fps(self) -> float:
        now = time.monotonic()
        self._update_times = [t for t in self._update_times if now - t < 3]
        return len(self._update_times) / 3

    # ---- worker -----------------------------------------------------------
    def _progress(self, value: float | None) -> None:
        self.upload_progress = value
        if self.on_progress:
            self.on_progress(value)

    async def _loop(self) -> None:
        while True:
            await self._changed.wait()
            self._changed.clear()
            while not self.device.connected:
                self._shown_job = None
                await asyncio.sleep(0.3)
            job = self._job
            if job is None or job is self._shown_job:
                continue
            if job[0] == "frame":
                ok = await self.device.send(p.CMD_STATIC_IMAGE, p.static_image_payload(job[1]))
            else:
                ok = await self._upload(job)
            if ok:
                self._shown_job = job
                self._update_times.append(time.monotonic())
            elif self._job is job:          # failed and nothing newer: retry shortly
                await asyncio.sleep(0.3)
                self._changed.set()
            if self._job is not job:
                self._changed.set()

    async def _upload(self, job) -> bool:
        _, data, first, settle = job
        # Show the first frame straight away as a still: instant, no loading symbol.
        await self.device.send(p.CMD_STATIC_IMAGE, p.static_image_payload(first))
        deadline = time.monotonic() + settle
        while time.monotonic() < deadline:
            if self._job is not job:
                return False
            await asyncio.sleep(0.05)
        if self._job is not job:
            return False
        size = len(data).to_bytes(4, "little")
        ready = await self.device.request(CMD_ANIMATION, b"\x00" + size, timeout=2.0)
        if ready is None:
            log.warning("device did not accept the animation upload")
            return False
        packets = [b"\x01" + size + (i // CHUNK).to_bytes(2, "little") + data[i:i + CHUNK]
                   for i in range(0, len(data), CHUNK)]
        t0 = time.monotonic()
        try:
            # 4 packets in flight: about twice as fast as waiting for every ACK (measured)
            ok = await self.device.send_stream(
                CMD_ANIMATION, packets, window=WINDOW, cancelled=lambda: self._job is not job,
                progress=lambda done: self._progress(done / len(packets)))
            if ok:
                log.info("uploaded animation: %d bytes in %d packets, %.1fs",
                         len(data), len(packets), time.monotonic() - t0)
            return ok
        finally:
            self._progress(None)
