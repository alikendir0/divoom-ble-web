"""Divoom Bluetooth framing and the 16x16 image encoder.

See docs/ditoo-plus-protocol.md for where each format comes from.
"""
from math import ceil, log2

Pixel = tuple[int, int, int]

# Bits per pixel for a palette of n colours (index = n).
_BITS = [0, 0] + [ceil(log2(n)) for n in range(2, 257)]


def plain_frame(cmd: int, payload: bytes = b"") -> bytes:
    """`01 LEN_LE16 CMD PAYLOAD CS_LE16 02` with no byte escaping ("NewMode")."""
    body = (len(payload) + 3).to_bytes(2, "little") + bytes([cmd]) + payload
    cs = sum(body) & 0xFFFF
    return b"\x01" + body + cs.to_bytes(2, "little") + b"\x02"


def ble_envelope(packet_no: int, cmd: int, payload: bytes = b"") -> bytes:
    """`FE EF AA 55 LEN_LE16 01 PKTNO_LE32 CMD PAYLOAD CS_LE16`, required over BLE."""
    body = b"\x01" + (packet_no & 0xFFFFFFFF).to_bytes(4, "little") + bytes([cmd]) + payload
    core = (len(body) + 2).to_bytes(2, "little") + body
    cs = sum(core) & 0xFFFF
    return b"\xfe\xef\xaa\x55" + core + cs.to_bytes(2, "little")


def split_replies(buf: bytes) -> tuple[list[bytes], bytes]:
    """Split a byte stream into complete `01 … 02` reply frames; return (frames, leftover)."""
    frames = []
    while True:
        start = buf.find(b"\x01")
        if start < 0:
            return frames, b""
        if len(buf) - start < 4:
            return frames, buf[start:]
        n = buf[start + 1] | buf[start + 2] << 8
        if len(buf) - start < n + 4:
            return frames, buf[start:]
        frames.append(buf[start:start + n + 4])
        buf = buf[start + n + 4:]


def parse_reply(frame: bytes) -> tuple[int, bytes] | None:
    """Return (cmd, data) for a `01 LEN 04 CMD 55 DATA CS 02` reply, else None."""
    if len(frame) < 9 or frame[3] != 0x04 or frame[5] != 0x55:
        return None
    return frame[4], frame[6:-3]


def encode_frame(pixels: list[Pixel], time_ms: int = 0, size: int = 16) -> bytes:
    """Encode one frame: `AA LEN TIME 00 N PALETTE BITS`.

    Palette is in first-appearance order; indices are packed LSB-first.
    """
    if len(pixels) != size * size:
        raise ValueError(f"expected {size * size} pixels, got {len(pixels)}")
    palette: dict[Pixel, int] = {}
    indices = []
    for p in pixels:
        p = (int(p[0]) & 255, int(p[1]) & 255, int(p[2]) & 255)
        if p not in palette:
            if len(palette) == 256:
                raise ValueError("more than 256 colours in one frame")
            palette[p] = len(palette)
        indices.append(palette[p])
    n = len(palette)
    bits = _BITS[n]
    packed = bytearray((size * size * bits + 7) // 8)
    pos = 0
    for idx in indices:
        for b in range(bits):
            if idx >> b & 1:
                packed[pos >> 3] |= 1 << (pos & 7)
            pos += 1
    colours = b"".join(bytes(c) for c in palette)
    length = 7 + len(colours) + len(packed)
    return (b"\xaa" + length.to_bytes(2, "little") + (time_ms & 0xFFFF).to_bytes(2, "little")
            + b"\x00" + bytes([n & 255]) + colours + bytes(packed))


def static_image_payload(pixels: list[Pixel]) -> bytes:
    """Payload for command 0x44 (show a static image)."""
    return b"\x00\x0a\x0a\x04" + encode_frame(pixels)


# Command opcodes used by the web controller.
CMD_STATIC_IMAGE = 0x44
CMD_SET_CHANNEL = 0x45
CMD_GET_CHANNEL = 0x46
CMD_SET_BRIGHTNESS = 0x74
CMD_GET_BRIGHTNESS = 0x31
CMD_ACK = 0x33          # BLE envelope ACK, data = packet number LE32
CMD_EXT = 0xBD


def channel_payload(kind: str, r: int = 255, g: int = 255, b: int = 255,
                    brightness: int = 100, effect: int = 0, index: int = 0) -> bytes:
    """Payload for 0x45 for the built-in channels."""
    if kind == "clock":
        return bytes([0x00, 0x01, index & 255, 1, 0, 0, 0, r, g, b])
    if kind == "light":
        return bytes([0x01, r, g, b, brightness, effect, 1, 0, 0, 0])
    if kind == "cloud":
        return b"\x02"
    if kind == "vj":
        return bytes([0x03, index & 255])
    if kind == "visualizer":
        return bytes([0x04, index & 255]) + bytes(8)
    if kind == "custom":
        return bytes([0x05, 0, 0, 0, 0, 0])
    raise ValueError(f"unknown channel {kind!r}")
