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
