"""Persistent BLE link to a Divoom pixel display (Pixoo, Ditoo, Timoo, ...).

One connection is kept open and re-established automatically. Every command is
wrapped in the BLE envelope and the device's 0x33 ACK is awaited, so commands
never pile up. Frames are "latest wins": while one frame is in flight, newer
frames replace each other and only the newest is sent next.
"""
import asyncio
import logging
import random
from collections.abc import Callable

from bleak import BleakClient, BleakScanner

from . import protocol as p

log = logging.getLogger(__name__)

WRITE_CHAR = "49535343-8841-43f4-a8d4-ecbe34729bb3"
NOTIFY_CHAR = "49535343-1e4d-4bd9-ba61-23c647249616"


_CONNECT_LOCK: asyncio.Lock | None = None


def _connect_lock() -> asyncio.Lock:
    global _CONNECT_LOCK
    if _CONNECT_LOCK is None:
        _CONNECT_LOCK = asyncio.Lock()
    return _CONNECT_LOCK


class DivoomDevice:
    def __init__(self, address: str, ack_timeout: float = 1.5, write_chunk: int = 244):
        self.address = address
        self.write_chunk = write_chunk          # bytes per BLE write (capped by the MTU)
        self.ack_timeout = ack_timeout
        self.connected = False
        self.on_status: Callable[[dict], None] | None = None   # called with {"connected": …} etc.
        self.on_reply: Callable[[int, bytes], None] | None = None
        self._client: BleakClient | None = None
        self._packet = random.randrange(1 << 20, 1 << 30)       # avoid reusing old packet numbers
        self._acks: dict[int, asyncio.Future] = {}
        self._waiters: dict[int, list[asyncio.Future]] = {}
        self._rx = b""
        self._write_lock = asyncio.Lock()
        self._tasks: list[asyncio.Task] = []

    # ---- lifecycle -------------------------------------------------------
    def start(self) -> None:
        self._tasks = [asyncio.create_task(self._connection_loop())]

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        if self._client and self._client.is_connected:
            await self._client.disconnect()

    def _set_connected(self, value: bool) -> None:
        if self.connected != value:
            self.connected = value
            log.info("%s %s", self.address, "connected" if value else "disconnected")
            if self.on_status:
                self.on_status({"connected": value})

    async def _connection_loop(self) -> None:
        delay = 1.0
        while True:
            if self._client and self._client.is_connected:
                await asyncio.sleep(1.0)
                continue
            self._set_connected(False)
            try:
                # one scan/connect at a time across devices: parallel BLE scans clash on Windows
                async with _connect_lock():
                    device = await BleakScanner.find_device_by_address(self.address, timeout=10)
                    if device is None:
                        raise ConnectionError("device not found (off, out of range, or connected elsewhere)")
                    client = BleakClient(device, timeout=20,
                                         disconnected_callback=lambda _c: self._set_connected(False))
                    await client.connect()
                    await client.start_notify(NOTIFY_CHAR, self._on_notify)
                self._client = client
                self._rx = b""
                self._set_connected(True)
                delay = 1.0
            except Exception as e:  # noqa: BLE001 - keep retrying whatever went wrong
                log.warning("%s: connect failed: %s; retrying in %.0fs", self.address, e, delay)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 15.0)

    # ---- receive ---------------------------------------------------------
    def _on_notify(self, _char, data: bytearray) -> None:
        frames, self._rx = p.split_replies(self._rx + bytes(data))
        for frame in frames:
            reply = p.parse_reply(frame)
            if reply is None:
                continue
            cmd, payload = reply
            if cmd == p.CMD_ACK and len(payload) >= 4:
                fut = self._acks.pop(int.from_bytes(payload[:4], "little"), None)
                if fut and not fut.done():
                    fut.set_result(None)
                continue
            for fut in self._waiters.pop(cmd, []):
                if not fut.done():
                    fut.set_result(payload)
            if self.on_reply:
                self.on_reply(cmd, payload)

    # ---- send ------------------------------------------------------------
    async def send(self, cmd: int, payload: bytes = b"") -> bool:
        """Send one command and wait for its ACK. Returns False if not connected or no ACK."""
        client = self._client
        if not (client and client.is_connected):
            return False
        async with self._write_lock:
            self._packet = (self._packet + 1) & 0xFFFFFFFF
            pkt = self._packet
            data = p.ble_envelope(pkt, cmd, payload)
            fut = asyncio.get_running_loop().create_future()
            self._acks[pkt] = fut
            # Write-without-response: with-response writes block until the device has
            # processed the command anyway, and the per-command ACK gives flow control.
            chunk = max(20, min(client.mtu_size - 3, self.write_chunk))
            try:
                for i in range(0, len(data), chunk):
                    await client.write_gatt_char(WRITE_CHAR, data[i:i + chunk], response=False)
                await asyncio.wait_for(fut, self.ack_timeout)
                return True
            except (asyncio.TimeoutError, Exception) as e:  # noqa: BLE001
                log.debug("send 0x%02X failed: %r", cmd, e)
                return False
            finally:
                self._acks.pop(pkt, None)

    async def send_stream(self, cmd: int, payloads: list[bytes], window: int = 4,
                          cancelled=lambda: False, progress=lambda done: None) -> bool:
        """Send many packets of one command with up to `window` unacknowledged at a time.

        Much faster than send() per packet for bulk uploads. Returns False if any packet
        is never acknowledged (after one retry) or `cancelled()` turns true.
        """
        client = self._client
        if not (client and client.is_connected):
            return False
        loop = asyncio.get_running_loop()
        in_flight: list[tuple[int, bytes, asyncio.Future]] = []
        chunk = max(20, min(client.mtu_size - 3, self.write_chunk))

        async def write(payload: bytes) -> tuple[int, bytes, asyncio.Future]:
            async with self._write_lock:
                self._packet = (self._packet + 1) & 0xFFFFFFFF
                pkt = self._packet
                fut = loop.create_future()
                self._acks[pkt] = fut
                data = p.ble_envelope(pkt, cmd, payload)
                for i in range(0, len(data), chunk):
                    await client.write_gatt_char(WRITE_CHAR, data[i:i + chunk], response=False)
            return pkt, payload, fut

        async def settle(entry) -> bool:
            pkt, payload, fut = entry
            try:
                await asyncio.wait_for(fut, self.ack_timeout)
                return True
            except asyncio.TimeoutError:
                return await self.send(cmd, payload)     # one plain retry
            finally:
                self._acks.pop(pkt, None)

        try:
            for n, payload in enumerate(payloads):
                if cancelled():
                    return False
                in_flight.append(await write(payload))
                if len(in_flight) >= window and not await settle(in_flight.pop(0)):
                    return False
                progress(n + 1 - len(in_flight))
            while in_flight:
                if not await settle(in_flight.pop(0)):
                    return False
            progress(len(payloads))
            return True
        except Exception as e:  # noqa: BLE001
            log.debug("stream 0x%02X failed: %r", cmd, e)
            return False
        finally:
            for pkt, _, _ in in_flight:
                self._acks.pop(pkt, None)

    async def request(self, cmd: int, payload: bytes = b"", reply_cmd: int | None = None,
                      timeout: float = 2.0) -> bytes | None:
        """Send a query and return the data of the matching reply, or None."""
        fut = asyncio.get_running_loop().create_future()
        key = cmd if reply_cmd is None else reply_cmd
        self._waiters.setdefault(key, []).append(fut)
        if not await self.send(cmd, payload):
            return None
        try:
            return await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError:
            return None
