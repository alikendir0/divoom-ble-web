"""Web server: browser UI over WebSocket plus a REST API for phones and scripts."""
import asyncio
import json
import logging
import socket
import time
from pathlib import Path

from aiohttp import WSMsgType, web

from . import protocol as p
from .device import DivoomDevice
from .display import Display
from .presets import PRESETS, PresetScene
from .scenes import ImageScene, PixelsScene, Scene, TextScene, ValueScene, parse_colour, to_hex

log = logging.getLogger(__name__)
STATIC = Path(__file__).parent / "static"
CHANNELS = ("clock", "light", "cloud", "vj", "visualizer", "custom")


class Controller:
    """Owns one device's current scene and pushes its frames to it and to every browser."""

    def __init__(self, device: DivoomDevice, key: str = "device", title: str = "Divoom"):
        self.key, self.title = key, title
        self.device = device
        self.display = Display(device)
        self.scene: Scene | None = None
        self.scene_started = 0.0
        self.frame: list[p.Pixel] = [(0, 0, 0)] * 256
        self.brightness: int | None = None
        self.channel: str | None = None          # set when a built-in channel is showing
        self.clients: set[web.WebSocketResponse] = set()
        self._next_render = 0.0
        self._own_command_at = 0.0
        self._last_progress_push = 0.0
        device.on_status = lambda st: asyncio.get_running_loop().create_task(self._on_link(st))
        device.on_reply = self._on_reply
        self.display.on_progress = self._on_progress

    def start(self) -> None:
        self.device.start()
        self.display.start()
        asyncio.create_task(self._render_loop())
        asyncio.create_task(self._status_loop())

    # ---- state ------------------------------------------------------------
    def state(self) -> dict:
        return {"type": "state", "connected": self.device.connected, "brightness": self.brightness,
                "scene": self.scene.describe() if self.scene else None, "channel": self.channel,
                "fps": round(self.display.fps, 1), "upload": self.display.upload_progress,
                "address": self.device.address, "device": self.key, "title": self.title}

    async def broadcast(self, msg: dict) -> None:
        data = json.dumps(msg)
        for ws in list(self.clients):
            try:
                await ws.send_str(data)
            except (ConnectionResetError, RuntimeError):
                self.clients.discard(ws)

    async def _on_link(self, status: dict) -> None:
        if status.get("connected"):
            reply = await self.device.request(p.CMD_GET_BRIGHTNESS)
            if reply:
                self.brightness = reply[0]
            self.display.invalidate()
        await self.broadcast(self.state())

    def _on_progress(self, value) -> None:
        now = time.monotonic()
        if value is None or now - self._last_progress_push > 0.25:
            self._last_progress_push = now
            asyncio.get_running_loop().create_task(self.broadcast(self.state()))

    def _on_reply(self, cmd: int, data: bytes) -> None:
        # A channel report we did not cause means someone pressed a button on the device:
        # hand the screen back to it instead of fighting the user.
        if cmd == p.CMD_GET_CHANNEL and len(data) >= 22 and time.monotonic() - self._own_command_at > 1.5:
            if self.scene is not None:
                log.info("device changed channel itself; releasing the screen")
                self.scene, self.channel = None, "device"
                self.display.release()
                asyncio.get_running_loop().create_task(self.broadcast(self.state()))
        # Brightness is only taken from our own 0x31 query (see _on_link): devices also
        # send unrelated 0x31/0x32 reports that are not it.

    # ---- scenes -----------------------------------------------------------
    async def set_scene(self, scene: Scene) -> None:
        self.scene, self.channel = scene, None
        self.scene_started = time.monotonic()
        self._next_render = 0.0
        frames = scene.loop()
        if frames:
            # the device plays it by itself; we only keep the browser preview moving.
            # Text and data change while someone types: wait for a pause before uploading.
            settle = 1.0 if isinstance(scene, (TextScene, ValueScene)) else 0.0
            self.display.play(frames, settle=settle)
            await self._render(force=True, to_device=False)
        else:
            await self._render(force=True)
        await self.broadcast(self.state())

    async def paint(self, changes: list) -> None:
        """Apply [[index, colour], …] on top of what is showing now."""
        base = list(self.frame)
        for idx, colour in changes:
            idx = int(idx)
            if not 0 <= idx < 256:
                raise ValueError(f"pixel index {idx} is outside 0-255 (index = y*16 + x)")
            base[idx] = parse_colour(colour)
        if isinstance(self.scene, PixelsScene):
            self.scene.frame = base
            await self._render(force=True)
        else:
            await self.set_scene(PixelsScene(base))

    async def _render(self, force: bool = False, to_device: bool = True) -> None:
        if self.scene is None:
            return
        frame = self.scene.render(time.monotonic() - self.scene_started)
        if force or frame != self.frame:
            self.frame = frame
            if to_device:
                self.display.show(frame)
            await self.broadcast({"type": "frame", "pixels": to_hex(frame)})

    async def _render_loop(self) -> None:
        while True:
            await asyncio.sleep(0.02)
            scene = self.scene
            if scene and scene.interval and time.monotonic() >= self._next_render:
                self._next_render = time.monotonic() + scene.interval
                await self._render(to_device=scene.live)

    async def _status_loop(self) -> None:
        while True:
            await asyncio.sleep(1.0)
            if self.clients:
                await self.broadcast(self.state())

    # ---- device settings --------------------------------------------------
    async def set_brightness(self, value: int) -> bool:
        value = max(0, min(100, int(value)))
        self._own_command_at = time.monotonic()
        ok = await self.device.send(p.CMD_SET_BRIGHTNESS, bytes([value]))
        if ok:
            self.brightness = value
        await self.broadcast(self.state())
        return ok

    async def set_channel(self, kind: str, color="#ffffff", index: int = 0, brightness: int = 100,
                          effect: int = 0) -> bool:
        if kind not in CHANNELS:
            raise ValueError(f"channel must be one of {', '.join(CHANNELS)}")
        r, g, b = parse_colour(color)
        self._own_command_at = time.monotonic()
        self.scene, self.channel = None, kind
        self.display.release()
        ok = await self.device.send(p.CMD_SET_CHANNEL, p.channel_payload(
            kind, r, g, b, brightness=int(brightness), effect=int(effect), index=int(index)))
        await self.broadcast(self.state())
        return ok

    # ---- one entry point for WebSocket and REST ---------------------------
    async def handle(self, msg: dict) -> dict:
        kind = msg.get("type")
        if kind == "pixels":
            await self.set_scene(PixelsScene(msg["pixels"]))
        elif kind == "paint":
            await self.paint(msg["changes"])
        elif kind == "fill":
            await self.set_scene(PixelsScene([parse_colour(msg.get("color"), (0, 0, 0))] * 256))
        elif kind == "text":
            await self.set_scene(TextScene(str(msg.get("text", "")), msg.get("color", "#ffffff"),
                                           msg.get("bg", "#000000"), msg.get("font", "big"),
                                           float(msg.get("speed", 14))))
        elif kind == "value":
            await self.set_scene(ValueScene(msg.get("value", ""), msg.get("label", ""),
                                            msg.get("color", "#ffffff"), msg.get("label_color", "#888888"),
                                            msg.get("bg", "#000000"), msg.get("bar"),
                                            msg.get("bar_color", "#00c8ff")))
        elif kind == "preset":
            await self.set_scene(PresetScene(str(msg["name"])))
        elif kind == "brightness":
            if not await self.set_brightness(msg["value"]):
                return {"ok": False, "error": "device did not acknowledge"}
        elif kind == "channel":
            if not await self.set_channel(msg["kind"], msg.get("color", "#ffffff"), msg.get("index", 0),
                                          msg.get("brightness", 100), msg.get("effect", 0)):
                return {"ok": False, "error": "device did not acknowledge"}
        elif kind == "redraw":
            self.display.invalidate()
        else:
            raise ValueError(f"unknown message type {kind!r}")
        return {"ok": True}


# ---- HTTP -------------------------------------------------------------------
def _ctl(request: web.Request) -> Controller:
    """The controller picked with ?device=<key>; the first configured device by default."""
    controllers: dict[str, Controller] = request.app["controllers"]
    key = request.query.get("device")
    if key is None:
        return next(iter(controllers.values()))
    if key not in controllers:
        raise ValueError(f"unknown device {key!r}; use one of {', '.join(controllers)}")
    return controllers[key]


def _check_token(request: web.Request) -> None:
    token = request.app["token"]
    if not token:
        return
    supplied = request.query.get("token") or request.headers.get("Authorization", "").removeprefix("Bearer ")
    if supplied != token:
        raise web.HTTPUnauthorized(text=json.dumps({"ok": False, "error": "bad or missing token"}),
                                   content_type="application/json")


@web.middleware
async def cors_and_errors(request: web.Request, handler):
    if request.method == "OPTIONS":
        resp = web.Response()
    else:
        try:
            resp = await handler(request)
        except web.HTTPException as e:
            resp = e
        except (ValueError, KeyError, TypeError, IndexError, OSError) as e:
            resp = web.json_response({"ok": False, "error": str(e) or type(e).__name__}, status=400)
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return resp


async def ws_handler(request: web.Request) -> web.WebSocketResponse:
    _check_token(request)
    ctl = _ctl(request)
    ws = web.WebSocketResponse(heartbeat=20)
    await ws.prepare(request)
    ctl.clients.add(ws)
    await ws.send_str(json.dumps(ctl.state()))
    await ws.send_str(json.dumps({"type": "frame", "pixels": to_hex(ctl.frame)}))
    try:
        async for m in ws:
            if m.type != WSMsgType.TEXT:
                continue
            try:
                result = await ctl.handle(json.loads(m.data))
            except (ValueError, KeyError, TypeError) as e:
                result = {"ok": False, "error": str(e)}
            if not result.get("ok"):
                await ws.send_str(json.dumps({"type": "error", "error": result.get("error")}))
    finally:
        ctl.clients.discard(ws)
    return ws


def _api(kind: str):
    async def handler(request: web.Request) -> web.Response:
        _check_token(request)
        body = await request.json() if request.can_read_body else {}
        result = await _ctl(request).handle({**body, "type": kind})
        return web.json_response(result, status=200 if result["ok"] else 502)
    return handler


async def api_state(request: web.Request) -> web.Response:
    _check_token(request)
    ctl = _ctl(request)
    return web.json_response({**ctl.state(), "frame": to_hex(ctl.frame)})


async def api_devices(request: web.Request) -> web.Response:
    _check_token(request)
    return web.json_response([{"device": c.key, "title": c.title, "address": c.device.address,
                               "connected": c.device.connected}
                              for c in request.app["controllers"].values()])


async def api_image(request: web.Request) -> web.Response:
    """Upload a picture or GIF: multipart field 'file', or the raw image as the body."""
    _check_token(request)
    fit = request.query.get("fit", "cover")
    if request.content_type.startswith("multipart/"):
        form = await request.post()
        field = form.get("file")
        if field is None or not hasattr(field, "file"):
            raise ValueError("multipart upload needs a 'file' field")
        data, name = field.file.read(), field.filename
        fit = form.get("fit", fit)
    else:
        data, name = await request.read(), "upload"
    if not data:
        raise ValueError("empty upload")
    await _ctl(request).set_scene(ImageScene(data, fit=fit, name=name))
    return web.json_response({"ok": True})


async def api_presets(request: web.Request) -> web.Response:
    return web.json_response([{"name": k, "title": v[0]} for k, v in PRESETS.items()])


async def index(_request: web.Request) -> web.FileResponse:
    return web.FileResponse(STATIC / "index.html")


def make_app(controllers: dict[str, Controller], token: str | None) -> web.Application:
    app = web.Application(middlewares=[cors_and_errors], client_max_size=16 * 1024 * 1024)
    app["controllers"], app["token"] = controllers, token
    app.router.add_get("/", index)
    app.router.add_get("/ws", ws_handler)
    app.router.add_get("/api/state", api_state)
    app.router.add_get("/api/devices", api_devices)
    app.router.add_get("/api/presets", api_presets)
    for kind in ("pixels", "paint", "fill", "text", "value", "preset", "brightness", "channel", "redraw"):
        app.router.add_post(f"/api/{kind}", _api(kind))
    app.router.add_post("/api/image", api_image)
    app.router.add_static("/static", STATIC)

    async def on_startup(_app):
        for ctl in controllers.values():
            ctl.start()

    async def on_cleanup(_app):
        for ctl in controllers.values():
            await ctl.device.stop()

    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    return app


def lan_addresses() -> list[str]:
    addrs = set()
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            addrs.add(s.getsockname()[0])
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            addrs.add(info[4][0])
    except OSError:
        pass
    return sorted(a for a in addrs if not a.startswith("127."))
