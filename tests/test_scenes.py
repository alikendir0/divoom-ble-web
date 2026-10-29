import io

import pytest
from PIL import Image

from divoom_ble.fonts import BIG, SMALL, render_text
from divoom_ble.scenes import ImageScene, PixelsScene, TextScene, ValueScene, parse_colour


def test_fonts_have_consistent_heights():
    assert all(len(g) == 7 for g in BIG.values())
    assert all(len(g) == 5 for g in SMALL.values())
    assert all(len({len(r) for r in g}) == 1 for g in list(BIG.values()) + list(SMALL.values()))


def test_render_text_width_includes_spacing():
    rows = render_text("HI", BIG)
    assert len(rows[0]) == 5 + 1 + 3


def test_parse_colour_forms():
    assert parse_colour("#ff8000") == (255, 128, 0)
    assert parse_colour("f80") == (255, 136, 0)
    assert parse_colour([1, 2, 300]) == (1, 2, 255)
    with pytest.raises(ValueError):
        parse_colour("#12")


def test_short_text_is_static_and_centred():
    s = TextScene("HI", color="#ff0000")
    assert s.interval == 0
    f = s.render(0)
    assert len(f) == 256 and (255, 0, 0) in f and f[0] == (0, 0, 0)


def test_long_text_scrolls():
    s = TextScene("HELLO WORLD", speed=10)
    assert s.interval > 0
    assert s.render(0) != s.render(0.5)


def test_value_widget_with_bar():
    s = ValueScene(72, label="BPM", bar=0.5, bar_color="#00ff00")
    f = s.render(0)
    assert f[15 * 16 + 0] == (0, 255, 0) and f[15 * 16 + 15] != (0, 255, 0)


def test_pixels_scene_rejects_wrong_size():
    with pytest.raises(ValueError):
        PixelsScene(["ffffff"] * 10)


def test_image_scene_scales_and_animates():
    frames = [Image.new("RGB", (32, 32), c) for c in ((255, 0, 0), (0, 0, 255))]
    buf = io.BytesIO()
    frames[0].save(buf, "GIF", save_all=True, append_images=frames[1:], duration=100, loop=0)
    s = ImageScene(buf.getvalue())
    assert len(s.frames) == 2 and s.interval > 0
    assert s.render(0)[0] == (255, 0, 0) and s.render(0.15)[0] == (0, 0, 255)


def test_scrolling_text_loop_is_seamless():
    s = TextScene("HELLO WORLD", speed=10)
    frames = s.loop()
    assert frames and len(frames) == round(s.loop_seconds / s.interval)
    assert frames[0][0] == s.render(s.loop_seconds)


def test_static_scenes_have_no_loop():
    assert TextScene("HI").loop() is None
    assert ValueScene("7").loop() is None


def test_two_scrolling_lines_share_one_loop():
    s = TextScene("FIRST LINE\nSECOND LONGER LINE", font="small", speed=10)
    frames = s.loop()
    assert frames[0][0] == s.render(s.loop_seconds)


def test_long_value_is_cut_off_not_scrolled():
    s = ValueScene("123456789", label="A VERY LONG LABEL")
    assert s.loop() is None and s.interval == 0
    assert len(s.render(0)) == 256
