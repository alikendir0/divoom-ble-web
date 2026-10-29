from divoom_ble.display import MAX_ANIMATION_BYTES, encode_animation, merge_repeats
from divoom_ble.protocol import encode_frame

BLACK, RED = (0, 0, 0), (255, 0, 0)


def test_merge_repeats_adds_durations():
    a, b = [BLACK] * 256, [RED] * 256
    assert merge_repeats([(a, 100), (a, 100), (b, 50), (a, 10)]) == [(a, 200), (b, 50), (a, 10)]


def test_encode_animation_concatenates_frames_with_their_times():
    a, b = [BLACK] * 256, [RED] * 256
    data = encode_animation([(a, 100), (b, 250)])
    assert data == encode_frame(a, 100) + encode_frame(b, 250)


def test_encode_animation_stays_under_budget():
    frames = [([(i, j, (i * j) % 256) for j in range(256)], 50) for i in range(120)]
    data = encode_animation(frames)
    assert len(data) <= MAX_ANIMATION_BYTES and data[0] == 0xAA
