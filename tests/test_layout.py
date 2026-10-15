import math

from iridia.layout import (fraction_to_stop, path_points, point_along, project, split_key,
                           stop_to_fraction, zone_count, zone_key)


def _strip(flip=False):
    return {"x": 0.0, "y": 0.0, "flip": flip,
            "segments": [{"start": 0, "angle": 0, "spacing": 10.0},
                         {"start": 3, "angle": 90, "spacing": 10.0}]}


def test_zone_key_roundtrip_with_dots():
    key = zone_key("Lian Li Uni Hub - AL v1.0", "Channel 1")
    assert split_key(key) == ("Lian Li Uni Hub - AL v1.0", "Channel 1")


def test_path_points_bends():
    pts = path_points(_strip(), 5)
    assert pts[0] == (0.0, 0.0)
    assert pts[2] == (20.0, 0.0)
    assert math.isclose(pts[4][0], 20.0, abs_tol=1e-9)
    assert math.isclose(pts[4][1], 20.0)


def test_point_along_and_project():
    pts = [(0.0, 0.0), (10.0, 0.0), (20.0, 0.0)]
    assert point_along(pts, 0.5) == (5.0, 0.0)
    assert point_along(pts, 99) == (20.0, 0.0)
    f, d = project(pts, 15.0, 3.0)
    assert math.isclose(f, 1.5) and math.isclose(d, 3.0)


def test_stop_fraction_roundtrip():
    for pattern in ("segments", "center_out", "edges_in"):
        for reverse in (False, True):
            for v in (0.0, 0.3, 0.8):
                f = stop_to_fraction(v, pattern, reverse, False)[0]
                assert math.isclose(fraction_to_stop(f, pattern, reverse, False), v, abs_tol=1e-9)


def test_zone_count():
    devs = {"Strip": {"zones": {"A": {"led_count": 30}}}, "Ram": {"led_count": 8}}
    assert zone_count(devs, zone_key("Strip", "A")) == 30
    assert zone_count(devs, zone_key("Strip", "B")) is None
    assert zone_count(devs, zone_key("Missing", "A")) is None


def test_a_wire_gap_moves_the_rest_of_the_strip():
    from iridia.layout import Layout, gap_starts
    s = {"x": 0.0, "y": 0.0, "segments": [{"start": 0, "angle": 0, "spacing": 10.0}]}
    assert Layout.add_cut(s, 3, 50.0)
    pts = path_points(s, 5)
    assert pts[2] == (20.0, 0.0) and pts[3] == (80.0, 0.0) and pts[4] == (90.0, 0.0)
    assert gap_starts(s, 5) == [3]
    Layout.reset_shape(s)                                   # straighten keeps the cut
    assert path_points(s, 5)[3] == (80.0, 0.0)
    Layout.set_gap(s, 1, 0)
    assert path_points(s, 5)[3] == (30.0, 0.0) and gap_starts(s, 5) == []


def test_hidden_sections_and_clean():
    from iridia.layout import Layout, hidden_path
    s = Layout._clean({"zone": "A|", "segments": [{"start": 0, "gap": 30, "hide": True},
                                                 {"start": 4, "angle": 90, "gap": "x"}]})
    assert "gap" not in s["segments"][0]                    # nothing before LED 1
    assert hidden_path(s, 6) == [True] * 4 + [False] * 2
    Layout.add_bend(s, 2)                                    # splitting a hidden part keeps it hidden
    assert hidden_path(s, 6) == [True] * 4 + [False] * 2
    Layout.set_section_hidden(s, 0, False)
    assert hidden_path(s, 6) == [False, False, True, True, False, False]


def test_clones_get_their_own_name(tmp_path):
    from iridia.layout import Layout
    lay = Layout(str(tmp_path / "layout.json"))
    lay.ensure_zones(["Dev|Z"])
    src = lay.strips[0]
    c = lay.clone(src["id"])
    assert "name" not in c
    c["name"] = "Shelf left"
    c2 = lay.clone(c["id"])
    assert "name" not in c2                                 # not copied from the strip it came from
    lay.labels = False
    lay.save()
    again = Layout(str(tmp_path / "layout.json"))
    assert again.get(c["id"])["name"] == "Shelf left" and again.labels is False
    assert "name" not in Layout._clean(dict(src, name="x"))  # only clones are named on their own
