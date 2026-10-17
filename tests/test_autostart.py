from iridia import autostart


def test_river_and_wayfire_lines(monkeypatch):
    river = autostart.snippet("river")["text"]
    assert "riverctl" not in river                      # river 0.4 refuses to start with it in the init
    assert river.split("\n")[0].endswith("iridia-daemon &")
    assert autostart.snippet("wayfire")["text"].startswith("[autostart]\niridia = ")
    for desk, sid in (("wayfire", "wayfire"), ("i3", "i3"), ("sway", "sway"), ("river", "river"), ("GNOME", "")):
        monkeypatch.setenv("XDG_CURRENT_DESKTOP", desk)
        for k in ("XDG_SESSION_DESKTOP", "HYPRLAND_INSTANCE_SIGNATURE", "NIRI_SOCKET", "SWAYSOCK", "I3SOCK"):
            monkeypatch.delenv(k, raising=False)
        assert autostart.detect_compositor() == sid


def test_compositor_found_by_its_process(tmp_path, monkeypatch):
    import os
    (tmp_path / "55").mkdir()
    (tmp_path / "55" / "comm").write_text("river\n")
    assert autostart._compositor_from_processes(str(tmp_path)) == "river"
    (tmp_path / "55" / "comm").write_text("bash\n")
    assert autostart._compositor_from_processes(str(tmp_path)) == ""
    assert os.path.exists(tmp_path)


def test_desktop_entry_exec_is_quoted():
    assert autostart._desktop_exec("/home/a b/iridia-daemon") == '"/home/a b/iridia-daemon"'
    assert autostart._desktop_exec("/home/x%y/iridia-daemon") == "/home/x%%y/iridia-daemon"
    assert "Exec=\"/home/a b/d\"" in autostart.xdg_desktop_entry("/home/a b/d")
