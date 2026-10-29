import json
import time

from clawd import (CLAUDE_ORANGE, FIVE_ROW, FIVE_TICKS, MARKER, STARS, TICK, TRACK, WEEK_ROW, WEEK_TICKS,
                              ClaudeUsageScene, ClawdScene, draw_clawd, elapsed_fraction, read_usage)


def usage(five, week):
    return {"five_hour_used": five, "seven_day_used": week, "five_hour_resets_at": None, "age_seconds": 0}


def test_read_usage_reports_used_percent(tmp_path):
    p = tmp_path / "cache.json"
    future = time.time() + 3600
    p.write_text(json.dumps({"fetched_at": time.time() - 10,
                             "five_hour": {"percent": 4, "resets_at": future},
                             "seven_day": {"percent": 37.6, "resets_at": future}}))
    u = read_usage(p)
    assert u["five_hour_used"] == 4 and u["seven_day_used"] == 38 and 9 <= u["age_seconds"] <= 11


def test_expired_window_counts_as_unused(tmp_path):
    p = tmp_path / "cache.json"
    p.write_text(json.dumps({"five_hour": {"percent": 90, "resets_at": time.time() - 1}}))
    assert read_usage(p)["five_hour_used"] == 0


def test_missing_file_gives_none(tmp_path):
    u = read_usage(tmp_path / "nope.json")
    assert u["five_hour_used"] is None and u["seven_day_used"] is None


def test_clawd_is_orange_and_animates():
    frames = [draw_clawd(t / 10) for t in range(40)]
    assert all(CLAUDE_ORANGE in f for f in frames)
    assert len({tuple(f) for f in frames}) >= 3
    s = ClawdScene()
    assert s.loop()[0][0] == s.render(s.loop_seconds)


NOW = 1_000_000


def full_usage(five, week, five_elapsed_h=None, week_elapsed_d=None, fetched_ago=30):
    u = usage(five, week)
    u["fetched_at"] = None if fetched_ago is None else NOW - fetched_ago
    u["five_hour_resets_at"] = None if five_elapsed_h is None else NOW + (5 - five_elapsed_h) * 3600
    u["seven_day_resets_at"] = None if week_elapsed_d is None else NOW + (7 - week_elapsed_d) * 86400
    return u


def _row(f, y):
    return f[y * 16:(y + 1) * 16]


def test_bars_fill_from_the_left_with_used_percent():
    f = ClaudeUsageScene(full_usage(60, 50), clock=lambda: NOW).render(0)
    assert _row(f, FIVE_ROW) == [(0, 0, 0)] + [CLAUDE_ORANGE] * 9 + [TRACK] * 6           # 15 px bar
    assert _row(f, WEEK_ROW) == [(0, 0, 0)] + [CLAUDE_ORANGE] * 7 + [TRACK] * 8   # 14 px + end cap


def test_every_hour_and_day_gets_the_same_number_of_pixels():
    def sections(width, ticks):
        edges = [1] + list(ticks) + [1 + width]
        return {b - a for a, b in zip(edges, edges[1:])}
    assert sections(15, FIVE_TICKS) == {3}       # 5 hours x 3 px
    assert sections(14, WEEK_TICKS) == {2}       # 7 days x 2 px


def test_time_marker_sits_at_elapsed_fraction():
    f = ClaudeUsageScene(full_usage(0, 0, five_elapsed_h=2.5, week_elapsed_d=3.5), clock=lambda: NOW).render(0)
    assert _row(f, FIVE_ROW).index(MARKER) == 1 + 7   # 2.5 h of 5 h: middle of the 15 px bar
    assert _row(f, WEEK_ROW).index(MARKER) == 1 + 7   # 3.5 d of 7 d: start of day 4 (2 px a day)


def test_tick_dots_tell_hours_from_days():
    f = ClaudeUsageScene(full_usage(0, 0), clock=lambda: NOW).render(0)
    assert sum(c == TICK for c in _row(f, FIVE_ROW + 1)) == 4     # 5 hours
    assert sum(c == TICK for c in _row(f, WEEK_ROW + 1)) == 6     # 7 days


def test_elapsed_fraction_bounds():
    assert elapsed_fraction(NOW + 5 * 3600, 5 * 3600, NOW) == 0
    assert elapsed_fraction(NOW - 10, 5 * 3600, NOW) == 1
    assert elapsed_fraction(None, 5 * 3600, NOW) is None


def test_stars_never_touch_clawd():
    s = ClaudeUsageScene(full_usage(0, 0), clock=lambda: NOW)
    for k in range(80):
        f = s.render(k / 10)
        for x, y, _ in STARS:
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    xx, yy = x + dx, y + dy
                    if (dx or dy) and 0 <= xx < 16 and 0 <= yy < 16:
                        assert f[yy * 16 + xx] != CLAUDE_ORANGE


def test_clawd_keeps_full_size_on_usage_screen():
    f = ClaudeUsageScene(full_usage(0, 0), clock=lambda: NOW).render(0.7)    # not bobbing up
    assert sum(c == CLAUDE_ORANGE for c in _row(f, 5)) == 14


def _eye_pixels(f):
    top = next(y for y in range(16) if f[y * 16 + 5] == CLAUDE_ORANGE)    # Clawd's head row
    return sum(f[y * 16 + x] == (0, 0, 0) for y in range(top, top + 8) for x in range(3, 13))


def test_clawd_squints_when_nearly_used_up():
    tired = ClaudeUsageScene(full_usage(90, 10), clock=lambda: NOW)
    fresh = ClaudeUsageScene(full_usage(10, 10), clock=lambda: NOW)
    assert all(_eye_pixels(tired.render(k / 10)) == 2 for k in range(0, 40, 3))   # 1-pixel eyes
    assert _eye_pixels(fresh.render(0.1)) == 4                                     # 2-pixel eyes


def test_usage_screen_animates_with_stills_in_four_colours():
    s = ClaudeUsageScene(full_usage(40, 50, 1, 1), clock=lambda: NOW)
    assert s.loop() is None and s.live
    frames = [s.render(k * s.interval) for k in range(32)]
    assert len({tuple(f) for f in frames}) > 1
    assert all(len(set(f)) <= 4 for f in frames)


def test_clawd_bobs_and_glances_on_usage_screen():
    s = ClaudeUsageScene(full_usage(10, 10), clock=lambda: NOW)
    head_rows = {next(y for y in range(16) if s.render(t)[y * 16 + 5] == CLAUDE_ORANGE) for t in (0.0, 0.5)}
    assert head_rows == {0, 1}                                   # bob
    def eye_columns(t):
        f = s.render(t)
        top = next(y for y in range(16) if f[y * 16 + 5] == CLAUDE_ORANGE)
        return {x for y in (top + 2, top + 3) for x in range(3, 13) if f[y * 16 + x] == (0, 0, 0)}
    assert eye_columns(0.75) == {5, 10} and eye_columns(4.75) == {4, 9} and eye_columns(5.75) == {6, 11}


def test_weekly_end_cap_lights_only_when_the_week_is_used_up():
    assert _row(ClaudeUsageScene(full_usage(0, 99), clock=lambda: NOW).render(0.25), WEEK_ROW)[15] == TRACK
    assert _row(ClaudeUsageScene(full_usage(0, 100), clock=lambda: NOW).render(0.25), WEEK_ROW)[15] != TRACK


def test_clawd_sleeps_when_the_data_is_old():
    s = ClaudeUsageScene(full_usage(10, 10, fetched_ago=20 * 60), clock=lambda: NOW)
    frames = [s.render(k / 4) for k in range(16)]
    assert all(_eye_pixels(f) == 2 for f in frames)                            # eyes shut
    tops = {next(y for y in range(16) if f[y * 16 + 5] == CLAUDE_ORANGE) for f in frames}
    assert tops == {1}                                                         # no bob
    assert any(f[2 * 16 + 13] == MARKER for f in frames)                       # a "z" floats up


def test_clawd_celebrates_fresh_data_then_calms_down():
    clock = [NOW]
    s = ClaudeUsageScene(full_usage(10, 10), clock=lambda: clock[0])
    newer = dict(s.usage, fetched_at=NOW)
    assert s.update(newer) and not s.update(newer)
    f = s.render(0.0)
    assert all(f[y * 16 + x] == MARKER for x, y, _ in STARS)                    # all stars on
    clock[0] = NOW + 3
    f = s.render(0.0)
    assert not all(f[y * 16 + x] == MARKER for x, y, _ in STARS)


def test_failed_fetch_keeps_last_good_numbers():
    s = ClaudeUsageScene(full_usage(40, 20), clock=lambda: NOW)
    broken = dict(s.usage, five_hour_used=None, seven_day_used=None, fetched_at=NOW)
    assert not s.update(broken)
    assert s.usage["five_hour_used"] == 40
