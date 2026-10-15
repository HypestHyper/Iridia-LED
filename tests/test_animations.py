import pytest

from iridia import animations as A

RED, BLUE, GREEN = (255, 0, 0), (0, 0, 255), (0, 255, 0)


@pytest.mark.parametrize("effect", A.ORDER)
def test_every_effect_gives_n_valid_colors_and_is_deterministic(effect):
    p = A.defaults(effect)
    for n in (1, 2, 80):
        for t in (0.0, 0.37, 12.5, 999.9):
            f = A.render(effect, p, n, t, [RED, BLUE], seed=3)
            assert len(f) == n
            assert all(len(c) == 3 and all(isinstance(v, int) and 0 <= v <= 255 for v in c) for c in f)
            assert f == A.render(effect, p, n, t, [RED, BLUE], seed=3)
    assert A.render(effect, p, 0, 1.0, [RED]) == []


def test_clean_clamps_and_ignores_unknown_keys():
    assert A.clean(None) is None and A.clean({"effect": "disco"}) is None
    c = A.clean({"effect": "breathing", "speed": 999, "min": 80, "max": 20, "easing": "bouncy", "x": 1})
    assert c["speed"] == 30.0 and (c["min"], c["max"]) == (20, 80) and c["easing"] == "sine"
    assert "x" not in c and c["sync"] is True and c["follow_layout"] is False
    assert A.clean({"effect": "comet", "heads": "3", "bounce": "yes"})["heads"] == 3
    assert A.clean({"effect": "comet", "bounce": "yes"})["bounce"] is False


def test_breathing_stays_between_min_and_max():
    p = A.clean({"effect": "breathing", "speed": 2, "min": 10, "max": 60, "cycle_colors": False})
    levels = [A.render("breathing", p, 1, t / 50, [(200, 200, 200)])[0][0] for t in range(200)]
    assert min(levels) == 20 and max(levels) == 120          # 10% and 60% of 200
    assert levels[0] == 20 and levels[50] == 120              # dark at the start, top halfway


def test_breathing_changes_color_at_the_dark_point():
    p = A.clean({"effect": "breathing", "speed": 2, "min": 0, "max": 100})
    assert A.render("breathing", p, 1, 1.0, [RED, BLUE])[0] == RED
    assert A.render("breathing", p, 1, 3.0, [RED, BLUE])[0] == BLUE


def test_breathing_without_cycling_breathes_the_static_pattern():
    p = A.clean({"effect": "breathing", "speed": 2, "min": 50, "max": 50, "cycle_colors": False})
    f = A.render("breathing", p, 2, 0.3, [RED, BLUE], base=[(200, 0, 0), (0, 0, 200)])
    assert f == [(100, 0, 0), (0, 0, 100)]


def test_speed_scales_time():
    slow = A.clean({"effect": "rainbow", "speed": 10})
    fast = A.clean({"effect": "rainbow", "speed": 20})
    assert A.render("rainbow", slow, 60, 2.0, []) == A.render("rainbow", fast, 60, 1.0, [])
    p2 = A.clean({"effect": "breathing", "speed": 2, "cycle_colors": False})
    p4 = A.clean({"effect": "breathing", "speed": 4, "cycle_colors": False})
    assert A.render("breathing", p2, 3, 0.5, [RED]) == A.render("breathing", p4, 3, 1.0, [RED])


def test_comet_head_moves_at_its_speed():
    p = A.clean({"effect": "comet", "speed": 10, "tail": 3, "heads": 1})
    def head(t):
        f = A.render("comet", p, 60, t, [RED])
        return max(range(60), key=lambda i: f[i][0])
    assert head(2.0) - head(1.0) == 10
    rev = A.clean({"effect": "comet", "speed": 10, "tail": 3, "reverse": True})
    f1, f2 = A.render("comet", rev, 60, 1.0, [RED]), A.render("comet", rev, 60, 2.0, [RED])
    assert max(range(60), key=lambda i: f1[i][0]) - max(range(60), key=lambda i: f2[i][0]) == 10


def test_fill_fills_then_empties():
    p = A.clean({"effect": "fill", "speed": 10, "pause": 1, "origin": "start", "empty": "reverse"})
    lit = lambda t: sum(1 for c in A.render("fill", p, 20, t, [RED], base=[RED] * 20) if c == RED)
    assert lit(0.0) == 0 and lit(1.0) == 10 and lit(2.5) == 20 and lit(4.0) == 10 and lit(5.5) == 0
    centre = A.clean({"effect": "fill", "speed": 10, "origin": "center"})
    f = A.render("fill", centre, 20, 0.5, [RED], base=[RED] * 20)
    assert f[10] == RED and f[0] != RED


def test_embers_differ_between_zones_but_not_between_calls():
    p = A.defaults("embers")
    a, b = A.render("embers", p, 50, 5.0, [], seed=1), A.render("embers", p, 50, 5.0, [], seed=2)
    assert a != b and a == A.render("embers", p, 50, 5.0, [], seed=1)
    reds = sum(c[0] for c in a) / 50
    assert reds > sum(c[2] for c in a) / 50                       # warm by default


def test_rainbow_ignores_the_zone_colors_and_covers_the_hues():
    p = A.clean({"effect": "rainbow", "width": 30})
    f = A.render("rainbow", p, 30, 0.0, [RED])
    assert len(set(f)) > 20
    assert A.clean({"effect": "rainbow", "saturation": 0}) and \
        set(A.render("rainbow", A.clean({"effect": "rainbow", "saturation": 0}), 10, 1, [])) == {(255, 255, 255)}


def test_color_cycle_holds_then_fades():
    p = A.clean({"effect": "color_cycle", "speed": 2, "hold": 1})
    assert A.render("color_cycle", p, 3, 0.5, [RED, BLUE]) == [RED] * 3
    mid = A.render("color_cycle", p, 1, 2.0, [RED, BLUE])[0]
    assert 0 < mid[0] < 255 and 0 < mid[2] < 255
    assert A.render("color_cycle", p, 1, 3.5, [RED, BLUE])[0] == BLUE


def test_positions_for_reverse_mirror_and_layout():
    assert A.strip_positions(4) == [0, 1, 2, 3]
    assert A.strip_positions(4, reverse=True) == [3, 2, 1, 0]
    assert A.strip_positions(5, mirror=True) == [0, 1, 2, 1, 0]
    pts = [(0, 0), (10, 0), (0, 10)]
    assert A.layout_positions(pts, 0, 10) == [0, 1, 0]
    assert [round(x) for x in A.layout_positions(pts, 90, 10)] == [0, 0, 1]


def test_follow_layout_uses_one_extent_for_all_strips():
    p = A.clean({"effect": "comet", "speed": 10, "tail": 2})
    left = A.render("comet", p, 10, 1.5, [RED], positions=[float(i) for i in range(10)], extent=(0, 20))
    right = A.render("comet", p, 10, 1.5, [RED], positions=[float(i) for i in range(10, 20)], extent=(0, 20))
    # at 1.5 s the head is around LED 14 of 20: in the right strip, not the left one
    assert max(c[0] for c in right) > 200 and max(c[0] for c in left) < 50
