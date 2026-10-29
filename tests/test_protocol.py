from divoom_ble.protocol import (ble_envelope, encode_frame, parse_reply, plain_frame,
                                split_replies, static_image_payload)


def test_plain_frame_matches_live_capture():
    # get volume, accepted by the Ditoo Plus
    assert plain_frame(0x09).hex() == "010300090c0002"
    # brightness 50
    assert plain_frame(0x74, b"\x32").hex() == "0104007432aa0002"


def test_ble_envelope_matches_live_capture():
    # get volume with packet 1, ACKed by the Ditoo Plus
    assert ble_envelope(1, 0x09).hex() == "feefaa550800010100000009" + "1300"
    # brightness 0 vector published by futpib for the Ditoo Pro
    assert ble_envelope(1, 0x74, b"\x00").hex() == "feefaa5509000101000000740" + "07f00"


def test_split_and_parse_replies():
    stream = bytes.fromhex("0109000433556b4c01004d0102" "010600043255" "35c60002" "01")
    frames, rest = split_replies(stream)
    assert len(frames) == 2 and rest == b"\x01"
    assert parse_reply(frames[0]) == (0x33, bytes.fromhex("6b4c0100"))
    assert parse_reply(frames[1]) == (0x32, b"\x35")


def test_single_colour_frame_has_no_pixel_bits():
    f = encode_frame([(255, 0, 0)] * 256)
    assert f.hex() == "aa0a0000000001ff0000"


def test_two_colour_frame_packs_lsb_first():
    px = [(0, 0, 0)] * 256
    px[1] = (255, 255, 255)
    f = encode_frame(px)
    assert f[:7] == bytes([0xAA, 7 + 6 + 32, 0, 0, 0, 0, 2])
    assert f[7:13] == bytes([0, 0, 0, 255, 255, 255])
    assert f[13] == 0b00000010 and len(f) == 7 + 6 + 32


def test_static_image_payload_header():
    assert static_image_payload([(1, 2, 3)] * 256)[:5] == bytes([0, 0x0A, 0x0A, 0x04, 0xAA])
