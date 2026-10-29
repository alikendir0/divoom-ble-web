# Divoom Bluetooth protocol notes

How this project talks to Divoom 16×16 displays. These notes are based on testing a Pixoo SlingBag and a Ditoo Plus, Divoom's public Bluetooth documentation, and other open-source projects. Behaviour on other models may differ.

## Transports

Dual-mode devices (with audio) show up twice: a classic Bluetooth name such as `Ditoo-Plus-audio-…`, and a BLE name such as `Ditoo-Plus-light-…`. Both use the same address.

| Transport | Details | Used here |
|---|---|---|
| **Bluetooth LE** | Service `49535343-fe7d-4ae5-8fa9-9fafd205e455`. Write to `49535343-8841-43f4-a8d4-ecbe34729bb3`; notifications arrive on `49535343-1e4d-4bd9-ba61-23c647249616`. | Yes |
| Classic RFCOMM (serial port) | Channel 1 on the devices tested. The same commands work with plain framing. | No |

A device accepts one controlling connection at a time.

## Framing

### Plain frame

```
01 | LEN_LO LEN_HI | CMD | PAYLOAD… | CS_LO CS_HI | 02
LEN = len(PAYLOAD) + 3
CS  = (LEN_LO + LEN_HI + CMD + sum(PAYLOAD)) & 0xFFFF
```

Newer devices need no byte escaping. Some old TimeBox models escape `01/02/03` as `03 04/05/06`.

### BLE envelope

Required over BLE. Plain frames written over BLE are ignored.

```
FE EF AA 55 | LEN LE16 | 01 | PKT LE32 | CMD | PAYLOAD… | CS LE16
LEN = 1 + 4 + 1 + len(PAYLOAD) + 2
CS  = sum of every byte after the 4-byte header
```

- **ACK:** the device sends `01 09 00 04 33 55 <PKT LE32> CS 02` for every frame, then any reply.
- **Packet number:** use a new `PKT` for every frame.
- **Writes:** write-without-response with ACK waiting gives the best throughput.

### Replies

```
01 LEN_LO LEN_HI 04 CMD 55 DATA… CS_LO CS_HI 02
```

`04` means a command reply and `55` means OK. Several replies can arrive in one notification; split them by `LEN`.

## Commands used by this project

| Cmd | Payload | Meaning |
|---|---|---|
| `0x44` | `00 0A 0A 04` + one frame | Show a still image. The device swaps it in all at once. |
| `0x8B` | see below | Upload an animation that the device then loops by itself |
| `0x45` | channel, then parameters | Switch to a built-in channel: `00` clock, `01` light, `02` cloud, `03` effects, `04` visualizer, `05` custom |
| `0x46` | none | Read channel and settings. The device also pushes an unrequested 22-byte report when its buttons change the channel. |
| `0x74` | brightness `0–100` | Set brightness. **Sending it with no payload sets the brightness from a stray byte.** Read the brightness with `0x31`. |
| `0x31` | none | Read brightness |
| `0xBD 13` | none | Animation capabilities. A reply starting `13 01` means `0x8B` is supported. |

Divoom's app defines about 150 more commands: alarms, timers, scoreboard, games, music, sleep, notifications and more. See Divoom's documentation and the projects listed at the end.

## Image frame encoding

One 16×16 frame:

```
AA | LEN LE16 | TIME_ms LE16 | 00 | N | N × (R G B) | pixel indices
LEN  = 7 + 3N + 32 × bits
bits = ceil(log2(N)), or 0 when N < 2
```

- **Palette:** colours in first-appearance order. `N = 256` is written as `00`.
- **Pixels:** row by row from the top left. Indices are packed LSB-first: bit `b` of pixel `i` goes to bit position `i × bits + b`.
- **Palette flag:** the `00` byte means each frame has its own palette. Keep it at `00`.
- **Speed:** fewer colours give smaller frames and faster ACKs. On the SlingBag, a still took about 55 ms with 2 colours, 360 ms with 8 and 800 ms with 256.

## Animation upload (`0x8B`)

1. Send `0x8B` with `00 | TOTAL LE32`. The device replies `8B …` when it's ready.
2. Send `0x8B` with `01 | TOTAL LE32 | INDEX LE16 | ≤256 bytes` for each chunk of the concatenated frames.

- **Pipelining:** keeping 4 packets in flight roughly halves the upload time. The device limits throughput to about 4 KB/s.
- **Loading symbol:** the device shows one for as long as the upload takes. Still images (`0x44`) never show it.
- **Older devices** use `0x49`: `TOTAL LE16 | INDEX u8 | ≤200 bytes`, with no handshake.

## Quirks

- **Drawing-pad mode flickers.** Mode `0x6F` fills the screen and `0x58` sets the pixels of one colour. Even small changes flicker visibly on the devices tested, and pixels set to pure black `(0,0,0)` are ignored, which leaves ghost pixels. Use `0x44` stills instead.
- **The first command after connecting** is sometimes dropped on RFCOMM. Over BLE the ACK makes any loss visible.
- **Button presses** produce unrequested replies, such as a volume reply (`09`) or a channel report (`46`). A controller can watch for these to notice them.

## Further reading

- Divoom's Bluetooth protocol documentation: <http://docin.divoom-gz.com>
- [d03n3rfr1tz3/hass-divoom](https://github.com/d03n3rfr1tz3/hass-divoom): Home Assistant integration
- [RomRider/node-divoom-timebox-evo](https://github.com/RomRider/node-divoom-timebox-evo): protocol write-up
- [futpib/divoom-ditoo-pro-controller](https://github.com/futpib/divoom-ditoo-pro-controller): command catalogue and the BLE envelope
