"""divoom-ble: real-time web control for Divoom 16x16 Bluetooth pixel displays.

    divoom-ble --scan                          find nearby devices
    divoom-ble --device AA:BB:CC:DD:EE:FF      serve the web page for one device
    divoom-ble --device bag=AA:...:FF=Backpack --device desk=11:...:22="Desk lamp"
"""
import argparse
import asyncio
import logging
import os

from aiohttp import web

from .device import DivoomDevice
from .server import Controller, lan_addresses, make_app

# Bluetooth names Divoom devices advertise (prefix match, case-insensitive).
DIVOOM_NAMES = ("pixoo", "ditoo", "timoo", "tivoo", "timebox", "divoom", "minitoo", "aurabox", "planet")


class DeviceSpec:
    """Parses 'MAC', 'name=MAC' or 'name=MAC=Title'; unnamed devices become device1, device2, ..."""

    def __init__(self):
        self.count = 0

    def __call__(self, spec: str) -> tuple[str, str, str]:
        self.count += 1
        parts = spec.split("=", 2)
        if len(parts) == 1:
            parts = [f"device{self.count}", parts[0]]
        name, mac = parts[0], parts[1].upper()
        if not name or len(mac.split(":")) != 6:
            raise argparse.ArgumentTypeError(f"expected MAC, name=MAC or name=MAC=Title, got {spec!r}")
        return name, mac, parts[2] if len(parts) == 3 else name


async def scan(seconds: float) -> list[tuple[str, str, int]]:
    """Return (name, address, rssi) for nearby devices that look like Divoom screens."""
    from bleak import BleakScanner
    found = await BleakScanner.discover(timeout=seconds, return_adv=True)
    rows = [(adv.local_name or d.name or "", addr, adv.rssi) for addr, (d, adv) in found.items()]
    return sorted((r for r in rows if r[0].lower().startswith(DIVOOM_NAMES)), key=lambda r: -r[2])


def main() -> None:
    ap = argparse.ArgumentParser(prog="divoom-ble",
                                 description="Real-time web control for Divoom 16x16 Bluetooth pixel displays")
    ap.add_argument("--scan", action="store_true", help="list nearby Divoom devices and exit")
    ap.add_argument("--device", action="append", type=DeviceSpec(), metavar="[NAME=]MAC[=TITLE]",
                    help="a device to control; repeat for several (or set DIVOOM_DEVICE)")
    ap.add_argument("--host", default="0.0.0.0", help="0.0.0.0 = reachable from other devices on your network")
    ap.add_argument("--port", type=int, default=int(os.environ.get("DIVOOM_PORT", 8080)))
    ap.add_argument("--token", default=os.environ.get("DIVOOM_TOKEN"),
                    help="if set, every API/WebSocket call must pass ?token=… or 'Authorization: Bearer …'")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("bleak").setLevel(logging.WARNING)

    if args.scan:
        print("Scanning for 10 s…")
        found = asyncio.run(scan(10))
        if not found:
            print("No Divoom devices found. Is the screen on, nearby, and closed in the phone app?")
            return
        for name, addr, rssi in found:
            print(f"  {addr}  {name}  (signal {rssi} dBm)")
        print(f"\nStart with:  divoom-ble --device {found[0][1]}")
        return

    devices = args.device or ([DeviceSpec()(os.environ["DIVOOM_DEVICE"])] if os.environ.get("DIVOOM_DEVICE") else [])
    if not devices:
        ap.error("tell me which device to use: --device AA:BB:CC:DD:EE:FF (find it with --scan)")

    controllers = {name: Controller(DivoomDevice(mac), name, title) for name, mac, title in devices}
    suffix = f"/?token={args.token}" if args.token else "/"
    print("Controlling " + ", ".join(f"{t} ({m})" for _, m, t in devices))
    print(f"  on this computer:  http://localhost:{args.port}{suffix}")
    for ip in lan_addresses():
        print(f"  on your network:   http://{ip}:{args.port}{suffix}")
    web.run_app(make_app(controllers, args.token), host=args.host, port=args.port, print=None)


if __name__ == "__main__":
    main()
