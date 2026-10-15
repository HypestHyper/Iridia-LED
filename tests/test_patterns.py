from iridia.patterns import PatternGenerator, even_boundaries, even_positions

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
