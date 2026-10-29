"""Show your Claude usage limits on a Divoom screen, with Clawd. Runs in the background, no web page.

    python examples/claude_usage/run.py --device AA:BB:CC:DD:EE:FF

The numbers come from a small JSON file (default: ~/.claude/divoom-usage.json) that
statusline_hook.py writes from Claude Code's status line. See README.md next to this file.
"""
import argparse
import asyncio
import logging
import logging.handlers
import shlex
import socket
import subprocess
import sys
import time
from pathlib import Path

from clawd import DEFAULT_USAGE_FILE, ClaudeUsageScene, read_usage

from divoom_ble import protocol as p
from divoom_ble.device import DivoomDevice
from divoom_ble.display import Display

log = logging.getLogger("claude_usage")

SINGLE_INSTANCE_PORT = 47616          # a localhost port held while the app runs
READ_EVERY = 20                       # re-read the usage file this often (s)
BUTTON_PAUSE = 60                     # after a button press on the screen, give it back for this long (s)


class UsageApp:
    def __init__(self, address: str, usage_file: Path, brightness: int | None,
                 refresh_cmd: list[str] | None, refresh_after: float):
        self.device = DivoomDevice(address)
        self.display = Display(self.device)
        self.usage_file = usage_file
        self.scene = ClaudeUsageScene(read_usage(usage_file))
        self.brightness = brightness
        self.refresh_cmd, self.refresh_after = refresh_cmd, refresh_after
        self.started = time.monotonic()
        self.paused_until = 0.0
        self.own_command_at = 0.0
        self.last_frame = None
        self.device.on_status = self._on_status
        self.device.on_reply = self._on_reply

    def _on_status(self, status: dict) -> None:
        if status.get("connected"):
            log.info("screen connected")
            self.last_frame = None                      # draw the current screen again
            self.display.invalidate()
            if self.brightness is not None:
                self.own_command_at = time.monotonic()  # its channel report is not a button press
                asyncio.get_running_loop().create_task(
                    self.device.send(p.CMD_SET_BRIGHTNESS, bytes([self.brightness])))
        else:
            log.info("screen disconnected; reconnecting in the background")

    def _on_reply(self, cmd: int, data: bytes) -> None:
        # An unrequested 22-byte channel report means a button was pressed on the screen.
        # Let the user have it for a while, then bring Clawd back.
        if cmd == p.CMD_GET_CHANNEL and len(data) >= 22 and time.monotonic() - self.own_command_at > 2:
            log.info("button pressed on the screen; pausing for %ds", BUTTON_PAUSE)
            self.paused_until = time.monotonic() + BUTTON_PAUSE
            self.display.release()
            self.last_frame = None

    async def render_loop(self) -> None:
        while True:
            await asyncio.sleep(self.scene.interval)
            if time.monotonic() < self.paused_until:
                continue
            frame = self.scene.render(time.monotonic() - self.started)
            if frame != self.last_frame:
                self.last_frame = frame
                self.display.show(frame)

    async def usage_loop(self) -> None:
        while True:
            usage = read_usage(self.usage_file)
            age = None if usage.get("fetched_at") is None else time.time() - usage["fetched_at"]
            if self.refresh_cmd and (age is None or age > self.refresh_after):
                await self._run_refresh()
                usage = read_usage(self.usage_file)
            if self.scene.update(usage):
                log.info("usage: 5-hour %s%% used, week %s%% used",
                         self.scene.usage["five_hour_used"], self.scene.usage["seven_day_used"])
            await asyncio.sleep(READ_EVERY)

    async def _run_refresh(self) -> None:
        try:
            proc = await asyncio.create_subprocess_exec(
                *self.refresh_cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            await asyncio.wait_for(proc.wait(), timeout=30)
        except (OSError, asyncio.TimeoutError) as e:
            log.warning("refresh command failed: %s", e)

    async def run(self) -> None:
        self.device.start()
        self.display.start()
        await asyncio.gather(self.render_loop(), self.usage_loop())


def hold_single_instance() -> socket.socket | None:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", SINGLE_INSTANCE_PORT))
        s.listen(1)
        return s
    except OSError:
        s.close()
        return None


def main() -> None:
    ap = argparse.ArgumentParser(description="Show Clawd and your Claude usage limits on a Divoom screen.")
    ap.add_argument("--device", required=True, metavar="MAC", help="the screen's Bluetooth address (divoom-ble --scan)")
    ap.add_argument("--usage-file", type=Path, default=DEFAULT_USAGE_FILE,
                    help=f"JSON written by statusline_hook.py (default: {DEFAULT_USAGE_FILE})")
    ap.add_argument("--refresh-cmd", metavar="COMMAND",
                    help="optional command that refreshes the usage file, run when it gets old "
                         "(lets the screen update while Claude Code is closed)")
    ap.add_argument("--refresh-after", type=float, default=150, metavar="SECONDS",
                    help="run --refresh-cmd when the file is older than this (default 150)")
    ap.add_argument("--brightness", type=int, choices=range(0, 101), metavar="0-100",
                    help="set the screen brightness on every connect")
    ap.add_argument("--log", type=Path, help="also log to this file (kept under 512 KB)")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    handlers: list[logging.Handler] = []
    if args.log:
        handlers.append(logging.handlers.RotatingFileHandler(args.log, maxBytes=256 * 1024, backupCount=1,
                                                             encoding="utf-8"))
    if sys.stderr is not None:                      # pythonw has no console
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, handlers=handlers or None,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("bleak").setLevel(logging.WARNING)

    lock = hold_single_instance()
    if lock is None:
        log.error("already running (port %d is taken); not starting a second copy", SINGLE_INSTANCE_PORT)
        sys.exit(1)
    refresh = shlex.split(args.refresh_cmd, posix=False) if args.refresh_cmd else None
    log.info("starting: screen %s, usage from %s", args.device, args.usage_file)
    try:
        asyncio.run(UsageApp(args.device.upper(), args.usage_file, args.brightness,
                             refresh, args.refresh_after).run())
    except KeyboardInterrupt:
        pass
    finally:
        lock.close()


if __name__ == "__main__":
    main()
