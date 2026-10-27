from iridia import notifyflash as nf
from iridia.sections import spans


def test_clean_repairs_junk():
    c = nf.clean({"effect": "boom", "duration": "99", "hex": "#ABCDEF", "apps": "?", "enabled": 1,
                  "targets": [{"device": "A", "start": 9, "end": 3}, {"device": "A", "start": 9, "end": 3},
                              {"device": ""}, "x", {"device": "B", "part": "2", "start": 1}]})
    assert c["effect"] == "pulse" and c["duration"] == 5.0 and c["hex"] == "abcdef" and c["apps"] == "all"
    assert c["enabled"] is True
    assert c["targets"] == [{"device": "A", "zone": "", "start": 3, "end": 9}, {"device": "B", "zone": "", "part": 2}]


def test_target_ranges():
    secs = [{"start": 0}, {"start": 4}, {"start": 7}]
    assert nf.target_range({"device": "A"}, 10, secs, spans) == (0, 10)
    assert nf.target_range({"part": 1}, 10, secs, spans) == (4, 7)
    assert nf.target_range({"part": 3}, 10, secs, spans) is None
    assert nf.target_range({"part": 0}, 10, [], spans) == (0, 10)
    assert nf.target_range({"start": 9, "end": 20}, 10, [], spans) == (8, 10)
    assert nf.target_range({"start": 11, "end": 20}, 10, [], spans) is None


def test_apps_filter_and_colors():
    st = nf.clean({"apps": "only", "app_list": ["Signal"]})
    assert nf.wanted(st, "signal") and not nf.wanted(st, "Thunderbird")
    assert nf.app_color("Signal") == nf.app_color("signal") != nf.app_color("Thunderbird")


def _lit(f, key, n, now):
    base = [(0, 0, 0)] * n
    return {i for i, c in enumerate(f.mix(key, base, now=now)) if c != (0, 0, 0)}


def test_every_effect_stays_on_its_leds_and_ends():
    for eff in nf.EFFECTS:
        leds = nf.led_places({"k": [(2, 8)]}, {}, eff, None)
        f = nf.Flash(leds, (0, 0, 255), eff, 1.0, now=0.0)
        base = [(10, 10, 10)] * 10
        assert f.mix("other", base, now=0.5) is base
        assert f.mix("k", base, now=1.0) is base and f.done(now=1.0)
        lit = set()
        for k in range(200):
            fr = f.mix("k", base, now=k / 200)
            assert fr[:2] == base[:2] and fr[8:] == base[8:]
            lit |= {i for i, c in enumerate(fr) if c != base[i]}
        assert lit == set(range(2, 8)), eff


def _head(f, n, now):
    fr = f.mix("k", [(0, 0, 0)] * n, now=now)
    return max(range(n), key=lambda i: fr[i][0])


def test_directions():
    leds = nf.led_places({"k": [(0, 20)]}, {}, "sweep", None)
    for d in ("ab", "ba"):
        f = nf.Flash(leds, (255, 0, 0), "sweep", 1.0, now=0.0, direction=d)
        assert (_head(f, 20, 0.25) < _head(f, 20, 0.75)) == (d == "ab")
    f = nf.Flash(leds, (255, 0, 0), "sweep", 1.0, now=0.0, direction="abba")
    assert _head(f, 20, 0.45) > 14 and _head(f, 20, 0.95) < 6          # there and back
    f = nf.Flash(leds, (255, 0, 0), "sweep", 1.0, now=0.0, direction="out", band=2)
    assert _lit(f, "k", 20, 0.05) <= set(range(7, 13))                  # starts in the middle
    assert _lit(f, "k", 20, 0.9) <= set(range(0, 3)) | set(range(17, 20))


def test_a_to_b_runs_through_the_room_and_leaves_out_what_is_outside():
    # two strips: one along y=0 from x=0 to 90, one along y=50 from x=0 to 90
    pos = {"s1": [[x * 10.0, 0.0] for x in range(10)], "s2": [[x * 10.0, 50.0] for x in range(10)]}
    path = {"a": [20.0, 0.0], "b": [70.0, 0.0]}
    leds = nf.led_places({"s1": [(0, 10)], "s2": [(0, 10)]}, pos, "sweep", path)
    t1 = {i: t for i, t, _s in leds["s1"]}
    assert list(t1) == list(range(2, 8))                                 # only between A and B
    assert t1[2] == 0.0 and t1[7] == 1.0
    assert t1 == {i: t for i, t, _s in leds["s2"]}                       # the wave crosses both at once
    # a strip not on the layout runs along its own LEDs
    leds = nf.led_places({"s1": [(0, 10)], "x": [(0, 4)]}, {"s1": pos["s1"], "x": None}, "sweep", path)
    assert [round(t, 3) for _i, t, _s in leds["x"]] == [0.125, 0.375, 0.625, 0.875]
    # pulse and flash light every chosen LED, A and B or not
    assert len(nf.led_places({"s1": [(0, 10)]}, pos, "pulse", path)["s1"]) == 10
    # the ripple: distance from A, with B on the edge
    rip = {i: t for i, t, _s in nf.led_places({"s1": [(0, 10)]}, pos, "ripple", path)["s1"]}
    assert rip[2] == 0.0 and rip[7] == 1.0 and rip[0] == 0.4 and 8 not in rip


def test_comet_has_a_tail_and_fill_fills():
    leds = nf.led_places({"k": [(0, 20)]}, {}, "comet", None)
    f = nf.Flash(leds, (255, 0, 0), "comet", 1.0, now=0.0, band=8)
    fr = f.mix("k", [(0, 0, 0)] * 20, now=0.5)
    h = max(range(20), key=lambda i: fr[i][0])
    assert fr[h - 2][0] > fr[h - 5][0] > 0 and fr[min(19, h + 2)][0] == 0   # tail behind, dark ahead
    f = nf.Flash(nf.led_places({"k": [(0, 20)]}, {}, "fill", None), (255, 0, 0), "fill", 1.0, now=0.0)
    assert _lit(f, "k", 20, 0.15) < _lit(f, "k", 20, 0.4) and len(_lit(f, "k", 20, 0.59)) == 20
    assert max(c[0] for c in f.mix("k", [(0, 0, 0)] * 20, now=0.999)) <= 1     # faded out


def test_repeat_and_brightness():
    leds = nf.led_places({"k": [(0, 4)]}, {}, "pulse", None)
    f = nf.Flash(leds, (200, 0, 0), "pulse", 1.0, now=0.0, repeat=3, brightness=50)
    assert not f.done(now=2.9) and f.done(now=3.0)
    assert f.mix("k", [(0, 0, 0)] * 4, now=2.25)[0] == (100, 0, 0)           # the third play, at half
    c = nf.clean({"repeat": 9, "brightness": 1, "band": 500})
    assert (c["repeat"], c["brightness"], c["band"]) == (5, 10, nf.BAND_MAX)


def test_app_rules_and_urgent():
    st = nf.clean({"effect": "pulse", "color": "custom", "hex": "0000ff", "urgent_effect": "flash",
                   "rules": [{"app": "Signal", "effect": "sweep", "color": "custom", "hex": "00ff00"},
                             {"app": "signal", "effect": "comet"}, {"app": "Mail", "color": "app"}, {"x": 1}]})
    assert [r["app"] for r in st["rules"]] == ["Signal", "Mail"]
    assert nf.style_for(st, "signal", False, "ffffff") == ("sweep", (0, 255, 0), False)
    assert nf.style_for(st, "Mail", False, "ffffff") == ("pulse", nf.app_color("Mail"), False)
    assert nf.style_for(st, "Other", False, "ffffff") == ("pulse", (0, 0, 255), False)
    assert nf.style_for(st, "Signal", True, "ffffff") == ("flash", nf.URGENT, False)
    st["urgent_red"] = False
    assert nf.style_for(st, "Signal", True, "ffffff") == ("flash", (0, 255, 0), False)


def test_painted_colours():
    st = nf.clean({"color": "painted", "paint": {"S|": {"1": "#FF0000", "2": "00ff00", "x": "0000ff", "3": "nope"},
                                                 "bad": {"1": "ffffff"}}})
    assert st["paint"] == {"S|": {"1": "ff0000", "2": "00ff00"}}
    assert nf.style_for(st, "Any", False, "123456") == ("pulse", (0x12, 0x34, 0x56), True)
    st["urgent_red"] = True
    assert nf.style_for(st, "Any", True, "123456")[2] is False           # urgent red wins
    leds = nf.led_places({"S|": [(0, 4)]}, {}, "pulse", None)
    f = nf.Flash(leds, (0, 0, 255), "pulse", 1.0, now=0.0, paint=nf.paint_rgb(st["paint"]))
    fr = f.mix("S|", [(0, 0, 0)] * 4, now=0.25)
    assert fr == [(0, 0, 255), (255, 0, 0), (0, 255, 0), (0, 0, 255)]     # unpainted ones: the colour given


def test_painted_leds_become_ranges():
    assert nf.targets_for("D", "Z", [5, 1, 2, 3, 9, 3]) == [
        {"device": "D", "zone": "Z", "start": 2, "end": 4}, {"device": "D", "zone": "Z", "start": 6, "end": 6},
        {"device": "D", "zone": "Z", "start": 10, "end": 10}]
    assert nf.clean({"path": {"a": [1, 2], "b": [3, "x"]}, "spatial": True})["spatial"] is False
    st = nf.clean({"path": {"a": [1, 2], "b": [3, 4]}, "spatial": True})
    assert st["path"] == {"a": [1.0, 2.0], "b": [3.0, 4.0]} and st["spatial"] is True


def test_the_band_is_a_number_of_leds_however_long_the_stretch():
    for n in (10, 20, 60, 150):
        for eff in ("sweep", "ripple"):
            leds = nf.led_places({"k": [(0, n)]}, {}, eff, None)
            f = nf.Flash(leds, (255, 0, 0), eff, 1.0, now=0.0, band=3)
            most = 0
            for k in range(400):
                fr = f.mix("k", [(0, 0, 0)] * n, now=k / 400)
                full = sum(1 for c in fr if c[0] >= 250)
                lit = sum(1 for c in fr if c[0] > 0)
                most = max(most, lit)                   # a ripple on a strip: two rings, both counted
                assert full <= (6 if eff == "ripple" else 3), (n, eff)
            assert most <= (10 if eff == "ripple" else 5), (n, eff, most)  # 3 LEDs and a soft LED each side


def test_between_a_and_b_the_band_is_counted_in_leds_too():
    pos = {"s": [[x * 10.0, 0.0] for x in range(40)]}
    leds = nf.led_places({"s": [(0, 40)]}, pos, "sweep", {"a": [0, 0], "b": [390, 0]}, {"s": 10.0})
    assert leds["s"][0][2] == 39.0                       # 39 LED gaps from A to B
    f = nf.Flash(leds, (255, 0, 0), "sweep", 1.0, now=0.0, band=4)
    fr = f.mix("s", [(0, 0, 0)] * 40, now=0.5)
    assert 3 <= sum(1 for c in fr if c[0] >= 250) <= 4
