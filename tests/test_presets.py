import pytest

from divoom_ble.presets import PRESETS, PresetScene


@pytest.mark.parametrize("name", list(PRESETS))
def test_every_preset_renders_valid_frames_over_time(name):
    scene = PresetScene(name)
    frames = [scene.render(t / 10) for t in range(0, 120, 3)]
    for f in frames:
        assert len(f) == 256
        assert all(len(c) == 3 and all(0 <= v <= 255 for v in c) for c in f)
    if name != "clock":
        assert len({tuple(f) for f in frames}) > 1, "preset should animate"


def test_unknown_preset_is_rejected():
    with pytest.raises(ValueError):
        PresetScene("nope")


@pytest.mark.parametrize("name", [n for n in PRESETS if n not in ("clock", "life")])
def test_preset_loops_are_seamless(name):
    scene = PresetScene(name)
    frames = scene.loop()
    assert frames[0][0] == scene.render(scene.loop_seconds)


def test_clock_is_live_not_uploaded():
    assert PresetScene("clock").loop() is None
