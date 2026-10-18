import pytest

from iridia.patterns import PatternGenerator, even_boundaries, even_positions, led_even_boundaries, segment_sizes

gen = PatternGenerator()
R, G, B = "ff0000", "00ff00", "0000ff"


def test_empty_and_unknown():
    assert gen.generate("solid", [R], 0) == []
    assert gen.generate("rainbow", [R], 3) == [R] * 3          # removed pattern -> solid
    assert gen.generate("solid", [], 2) == ["642107"] * 2       # no colours -> fallback


def test_segments_even():
    assert gen.generate("segments", [R, G], 4) == [R, R, G, G]


def test_segments_custom_stops_and_bad_stops():
    assert gen.generate("segments", [R, G], 4, params={"stops": [0.25]}) == [R, G, G, G]
    # Wrong length or junk falls back to even spacing
    assert gen.generate("segments", [R, G], 4, params={"stops": [0.1, 0.2]}) == [R, R, G, G]
    assert gen.generate("segments", [R, G], 4, params={"stops": ["x"]}) == [R, R, G, G]


def test_gradient_endpoints():
    out = gen.generate("gradient", ["000000", "ffffff"], 3)
    assert out[0] == "000000" and out[-1] == "ffffff"
    assert out[1] == "808080"


def test_reverse_and_mirror():
    assert gen.generate("segments", [R, G], 4, params={"reverse": True}) == [G, G, R, R]
    assert gen.generate("segments", [R, G], 4, params={"mirror": True}) == [R, G, G, R]
    assert gen.generate("segments", [R, G], 5, params={"mirror": True}) == [R, G, G, G, R]


def test_center_out_and_edges_in():
    assert gen.generate("center_out", [R, G], 4) == [G, R, R, G]
    assert gen.generate("edges_in", [R, G], 4) == [R, G, G, R]


def test_alternating():
    assert gen.generate("alternating", [R, G, B], 5) == [R, G, B, R, G]


def test_paint():
    params = {"paint": ["#FF0000", None, "bad"]}
    assert gen.generate("paint", [B], 4, params=params) == [R, B, B, B]


def test_stop_helpers():
    assert even_boundaries(3) == [1 / 3, 2 / 3]
    assert even_positions(1) == [0.0]
    assert even_positions(3) == [0.0, 0.5, 1.0]
    assert PatternGenerator.handle_count("gradient", 3) == 3
    assert PatternGenerator.handle_count("segments", 3) == 2
    assert PatternGenerator.handle_count("solid", 3) == 0


def test_space_evenly_counts_whole_leds():
    for leds, parts, want in ((80, 3, [27, 27, 26]), (30, 4, [8, 8, 7, 7]), (40, 5, [8] * 5), (5, 3, [2, 2, 1])):
        stops = led_even_boundaries(parts, leds)
        assert segment_sizes(stops, parts, leds) == want
        drawn = PatternGenerator().generate("segments", [f"{k:06x}" for k in range(parts)], leds, params={"stops": stops})
        assert [drawn.count(f"{k:06x}") for k in range(parts)] == want
    assert segment_sizes([0.3, 0.62], 3, 20) == [6, 6, 8]
    assert segment_sizes(None, 2, 7) == [3, 4]


def test_window_sizes_scale_the_stylesheet():
    style = pytest.importorskip("iridia.ui.style")
    css = "a { min-height: 40px; border: 1px solid; margin: -12px 2px; border-radius: 999px; font-size: 14px; }"
    assert style.scale_px(css, 1) == css
    assert style.scale_px(css, 0.8) == ("a { min-height: 32px; border: 1px solid; margin: -9.6px 2px; "
                                        "border-radius: 999px; font-size: 12.3px; }")
    assert "font-size: 10px" in style.scale_px("x { font-size: 11px; }", 0.5)      # text never below 10px
    assert style.scale_px("x { font-size: 9px; }", 0.5) == "x { font-size: 9px; }"
