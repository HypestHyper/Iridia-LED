"""Scenes: which look shows for what's in front, the delays, and reading each desktop's answer."""
import os

from iridia import focuswatch as F
from iridia import scenes as S


def test_clean_and_looks():
    st = S.clean({"enabled": True, "scenes": [
        {"name": "Films", "when": "apps", "apps": ["mpv", "MPV", ""], "look": {"kind": "off"}},
        {"name": "x", "look": {"kind": "disco"}},                                   # no look: dropped
        {"name": "Games", "look": {"kind": "color", "hex": "#FF8800", "bright": 250}, "targets": ["A|b", "nope"]},
        {"name": "None", "look": {"kind": "off"}, "targets": []}],                  # no strips: dropped
        "ignore": ["Firefox", "firefox", ""], "on_delay": -3, "interval": 99})
    films, games = st["scenes"]
    assert films["apps"] == ["mpv"] and films["when"] == "apps" and films["on"] and films["targets"] == ["*"]
    assert games["look"] == {"kind": "color", "hex": "ff8800", "bright": 100} and games["targets"] == ["A|b"]
    assert games["when"] == "fullscreen" and games["apps"] == []
    assert st["ignore"] == ["Firefox"] and st["on_delay"] == 0.0 and st["interval"] == 30
    first = S.clean({})
    assert not first["enabled"] and [x["look"] for x in first["scenes"]] == [{"kind": "dim", "bright": 20}]
    assert S.clean({"scenes": []})["scenes"] == []
    assert S.clean_look({"kind": "effect", "effect": "nope"})["effect"] == "breathing"
    assert S.overlay({"kind": "off"}) == {"power": "off"}
    assert S.overlay({"kind": "dim", "bright": 20}) == {"bright": 20}
    assert S.overlay({"kind": "effect", "effect": "rainbow", "bright": 80})["effect"]["effect"] == "rainbow"


def test_older_settings_become_scenes():
    old = {"enabled": True, "look": {"kind": "dim", "bright": 10},
           "apps": [{"app": "mpv", "look": {"kind": "off"}}, {"app": "MPV", "look": {"kind": "dim"}}]}
    st = S.clean(old)
    assert [(x["name"], x["when"], x["apps"]) for x in st["scenes"]] == [
        ("mpv", "apps", ["mpv"]), ("Anything fullscreen", "fullscreen", [])]
    assert [x["id"] for x in S.clean(old)["scenes"]] == [x["id"] for x in st["scenes"]]   # the same each time
    assert S.clean({"look": None})["scenes"] == []                          # had nothing for fullscreen


def test_pick_in_order():
    st = S.clean({"enabled": True, "ignore": ["firefox"], "scenes": [
        {"id": "aaaa", "when": "apps", "apps": ["steam_app_1091500"], "look": {"kind": "effect", "effect": "embers"}},
        {"id": "bbbb", "when": "fullscreen", "look": {"kind": "dim", "bright": 10}},
        {"id": "cccc", "when": "apps", "apps": ["obs"], "look": {"kind": "off"}, "on": False}]})
    assert S.pick(st, "Steam_App_1091500", False) == ("aaaa",)            # in front, fullscreen or not
    assert S.pick(st, "Steam_App_1091500", True) == ("aaaa", "bbbb")      # both; the first wins where they meet
    assert S.pick(st, "mpv", True) == ("bbbb",)
    assert S.pick(st, "mpv", False) == ()
    assert S.pick(st, "firefox", True) == ()                               # ignored
    assert S.pick(st, "obs", True) == ("bbbb",)                            # a scene switched off
    assert S.pick(st, "", False, running={"steam_app_1091500"}) == ("aaaa",)   # fallback: running
    assert S.pick(dict(st, enabled=False), "mpv", True) == ()
    assert S.watched_apps(st) == ["steam_app_1091500"] and S.needs_watching(st)


def test_delay_keeps_a_quick_alt_tab_from_flickering():
    d, on, off = S.Delay(), 1.0, 2.0
    a = ("a1",)
    assert d.update(a, 0.0, on, off) == ()
    assert d.update(a, 1.0, on, off) == a                  # on after 1 s
    assert d.update((), 5.0, on, off) == a                 # alt-tab out...
    assert d.update(a, 6.0, on, off) == a                  # ...and back within 2 s: no change
    assert d.update((), 7.0, on, off) == a
    assert d.update((), 9.0, on, off) == ()                # gone for 2 s: back to normal


def test_hyprland_answers():
    assert F.hypr_state({"class": "mpv", "fullscreen": 2}) == ("mpv", True)
    assert F.hypr_state({"class": "kitty", "fullscreen": 1}) == ("kitty", False)       # maximised
    assert F.hypr_state({"class": "mpv", "fullscreen": True, "fullscreenMode": 0}) == ("mpv", True)
    assert F.hypr_state({"class": "mpv", "fullscreen": True, "fullscreenMode": 1}) == ("mpv", False)
    assert F.hypr_state({}) == ("", False)


def test_sway_events():
    cur = ("", False, -1)
    ev = {"change": "focus", "container": {"id": 7, "app_id": None, "focused": True, "fullscreen_mode": 0,
                                           "window_properties": {"class": "steam_app_10"}}}
    cur = F.sway_event(ev, cur)
    assert cur == ("steam_app_10", False, 7)
    ev = {"change": "fullscreen_mode", "container": {"id": 7, "app_id": "x", "focused": True, "fullscreen_mode": 1}}
    assert F.sway_event(ev, cur) == ("x", True, 7)
    assert F.sway_event({"change": "close", "container": {"id": 3}}, cur) is None      # another window
    assert F.sway_event({"change": "close", "container": {"id": 7}}, cur) == ("", False, -1)


def test_x11_answers():
    assert F.xprop_active("_NET_ACTIVE_WINDOW(WINDOW): window id # 0x3a00007") == "0x3a00007"
    assert F.xprop_active("_NET_ACTIVE_WINDOW(WINDOW): window id # 0x0") is None
    out = ('_NET_WM_STATE(ATOM) = _NET_WM_STATE_FULLSCREEN, _NET_WM_STATE_FOCUSED\n'
           'WM_CLASS(STRING) = "steam_app_570", "steam_app_570"\n')
    assert F.xprop_window(out) == ("steam_app_570", True)
    assert F.xprop_window('WM_CLASS(STRING) = "navigator", "firefox"\n') == ("firefox", False)


def test_running_programs(tmp_path):
    def proc(pid, *args):
        p = tmp_path / str(pid)
        p.mkdir()
        (p / "cmdline").write_bytes(b"\0".join(a.encode() for a in args) + b"\0")
    proc(10, "/usr/bin/mpv", "film.mkv")
    proc(11, "/home/u/.steam/ubuntu12_32/reaper", "SteamLaunch", "AppId=1091500", "--", "x")
    proc(12, "Z:\\Games\\Cyberpunk2077.exe")
    (tmp_path / "self").mkdir()
    apps = F.running_apps(str(tmp_path))
    assert {"mpv", "steam_app_1091500", "Cyberpunk2077"} <= apps


def test_kwin_script_names_the_bus():
    assert F.BUS_NAME in F.kwin_script() and "fullScreenChanged" in F.kwin_script()
    assert "DEBUG = false" in F.kwin_script() and "DEBUG = true" in F.kwin_script(debug=True)
    assert os.path.basename(F.BUS_PATH) == "Focus"


def test_hyprland_watcher_with_fake_sockets(tmp_path, monkeypatch):
    import json
    import socket
    import threading
    import time
    base = tmp_path / "hypr" / "sig"
    base.mkdir(parents=True)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setenv("HYPRLAND_INSTANCE_SIGNATURE", "sig")
    state = {"class": "kitty", "fullscreen": 0}
    req = socket.socket(socket.AF_UNIX)
    req.bind(str(base / ".socket.sock"))
    req.listen(5)
    ev = socket.socket(socket.AF_UNIX)
    ev.bind(str(base / ".socket2.sock"))
    ev.listen(1)

    def answer():
        while True:
            try:
                c, _ = req.accept()
            except OSError:
                return
            c.recv(100)
            c.sendall(json.dumps(state).encode())
            c.close()
    threading.Thread(target=answer, daemon=True).start()
    changes = []
    w = F.FocusWatch(lambda: changes.append((w.front, w.fullscreen)))
    assert w.pick_method() == "hyprland"
    w.set_needed(True)
    conn, _ = ev.accept()

    def wait(pred):
        end = time.monotonic() + 3
        while time.monotonic() < end and not pred():
            time.sleep(0.02)
        return pred()
    assert wait(lambda: changes and changes[-1] == ("kitty", False))
    state.update({"class": "steam_app_10", "fullscreen": 2})
    conn.sendall(b"activewindow>>steam_app_10,Game\nfullscreen>>1\n")
    assert wait(lambda: changes[-1] == ("steam_app_10", True))
    w.stop()
    conn.close()
    req.close()
    ev.close()
    assert not w.running_flag and w.front == ""


def test_a_failed_try_is_cleaned_up_before_the_next(monkeypatch):
    w = F.FocusWatch(lambda: None)
    calls = []

    def boom(gen):
        w._stop_hooks.append(lambda: calls.append("cleaned"))
        w._gen += 1                           # stop after this try
        raise OSError("KWin said no")
    monkeypatch.setattr(w, "_loop_kde", boom, raising=False)
    w._gen = 1
    w._run("kde", 1)
    assert calls == [] and w._stop_hooks       # stopped meanwhile: stop() cleans up instead
    w._gen = 5

    def boom2(gen):
        w._stop_hooks.append(lambda: calls.append("cleaned"))
        raise OSError("KWin said no")
    monkeypatch.setattr(w, "_loop_kde", boom2, raising=False)
    monkeypatch.setattr(F.time, "sleep", lambda s: setattr(w, "_gen", 99))
    w._run("kde", 5)
    assert "cleaned" in calls
