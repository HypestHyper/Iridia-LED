from iridia import sessionwatch as W


def test_parsing_gdbus_answers():
    assert W.parse_bool("(<true>,)") is True and W.parse_bool("(false,)") is False and W.parse_bool("") is None
    assert W.parse_number("(uint64 12345,)") == 12345 and W.parse_number("(<uint64 1700000000000000>,)") == \
        1700000000000000 and W.parse_number("(uint32 7,)") == 7 and W.parse_number("nope") is None
    assert W.parse_object_path("(<('2', objectpath '/org/freedesktop/login1/session/_32')>,)") == \
        "/org/freedesktop/login1/session/_32"
    assert W.parse_object_path("(objectpath '/org/freedesktop/login1/session/c1',)") == \
        "/org/freedesktop/login1/session/c1"


def test_lock_events_from_monitors():
    ev = W.lock_event
    assert ev("/org/freedesktop/login1/session/_32: org.freedesktop.DBus.Properties.PropertiesChanged "
              "('org.freedesktop.login1.Session', {'LockedHint': <true>}, @as [])") == ("locked", None)
    assert ev("... PropertiesChanged ('org.freedesktop.login1.Session', {'LockedHint': <false>}, @as [])") == \
        ("unlocked", None)
    assert ev("... PropertiesChanged ('org.freedesktop.login1.Session', {'IdleHint': <true>}, @as [])") == \
        (None, None)
    assert ev("/org/freedesktop/login1/session/_32: org.freedesktop.login1.Session.Lock ()") == ("lock", None)
    assert ev("/org/freedesktop/login1/session/_32: org.freedesktop.login1.Session.Unlock ()") == ("unlock", None)
    # dbus-monitor: the argument comes on the next line
    first = "signal time=1.2 sender=:1.5 -> destination=(null destination) serial=9 path=/ScreenSaver; " \
            "interface=org.freedesktop.ScreenSaver; member=ActiveChanged"
    assert ev(first) == (None, "active")
    assert ev("   boolean true", "active") == ("locked", None)
    assert ev("   boolean false", "active") == ("unlocked", None)
    assert ev("/org/gnome/ScreenSaver: org.gnome.ScreenSaver.ActiveChanged (true,)") == ("locked", None)


def test_locked_combines_what_the_desktop_says_and_the_locker():
    w = W.SessionWatcher(lambda: None)
    w.watching_lock = True
    assert not w.locked
    w._locker_running = True
    assert w.locked
    w._locker_running, w._said_locked = False, True
    assert w.locked
    assert w.idle_seconds() is None                 # nothing asked for it


def test_finds_a_screen_locker_in_proc(tmp_path):
    import os
    for pid, name in (("12", "bash"), ("40", "hyprlock"), ("abc", "swaylock"), ("7", "betterlockscree")):
        (tmp_path / pid).mkdir()
        (tmp_path / pid / "comm").write_text(name + "\n")
    assert W.find_locker(str(tmp_path), os.getuid()) in ("hyprlock", "betterlockscree")
    assert W.find_locker(str(tmp_path), os.getuid() + 1) is None       # someone else's
    assert W.find_locker(str(tmp_path / "missing"), os.getuid()) is None


def test_nothing_runs_until_something_is_switched_on(monkeypatch):
    import threading
    started = []
    real = threading.Thread

    class Spy(real):
        def start(self):
            started.append(self.name)
            super().start()
    monkeypatch.setattr(W.threading, "Thread", Spy)
    monkeypatch.setattr(W.shutil, "which", lambda exe: None)              # no gdbus, no dbus-monitor
    monkeypatch.setattr(W.SessionWatcher, "_find_session", staticmethod(lambda: None))
    changes = []
    w = W.SessionWatcher(lambda: changes.append(1))
    w.start()
    w.set_needs(lock=False, idle=False)
    assert started == [] and not w.watching_lock and not w.want_idle
    w.set_needs(lock=True, idle=False)
    assert w.watching_lock and started[0] == "sessionwatch"
    w.set_needs(lock=True, idle=False)                                    # no second start
    assert started.count("sessionwatch") == 1
    w._locker_running = True
    w.set_needs(lock=False, idle=True)                                    # lock off: forgets it, idle on
    assert not w.locked and not w._locker_running and w.want_idle
    assert "sessionwatch-idle" in started
    w.set_needs(lock=False, idle=False)
    assert not w.want_idle and w.idle_seconds() is None
    w.stop()


def test_only_screen_savers_count_as_locking():
    ev = W.lock_event
    other = "signal time=1.2 sender=:1.9 -> destination=(null destination) serial=4 path=/Player; " \
            "interface=org.example.Player; member=ActiveChanged"
    assert W.screensaver_of(other) is None and ev(other) == (None, None)
    assert ev("/org/example: org.example.Thing.ActiveChanged (true,)") == (None, None)
    for iface in W.SCREENSAVERS:
        assert W.screensaver_of(f"path=/x; interface={iface}; member=ActiveChanged") == iface
    assert W.screensaver_of("/org/cinnamon/ScreenSaver: org.cinnamon.ScreenSaver.ActiveChanged (true,)") == \
        "org.cinnamon.ScreenSaver"


def test_a_missed_unlock_is_noticed(monkeypatch):
    changes = []
    w = W.SessionWatcher(lambda: changes.append(1))
    w.watching_lock = True
    w._said_locked, w._said_by = True, "org.freedesktop.ScreenSaver"
    answers = iter([True, None, False])                 # still locked, no answer, unlocked
    monkeypatch.setattr(w, "_still_said_locked", lambda: next(answers))
    for expect in (True, True, False):
        w._verify_at = 0.0
        w._verify()
        assert w.locked is expect
    assert changes == [1]
    w._said_locked, w._verify_at = True, W.time.monotonic() + 60
    w._verify()                                         # not due yet: nothing asked
    assert w.locked


def test_asks_the_one_that_said_locked(monkeypatch):
    calls = []
    monkeypatch.setattr(W, "_gdbus_call", lambda *a: calls.append(a) or "(false,)")
    w = W.SessionWatcher(lambda: None)
    w._said_by = "org.gnome.ScreenSaver"
    assert w._still_said_locked() is False
    assert calls[-1][1:] == ("org.gnome.ScreenSaver", "/org/gnome/ScreenSaver", "org.gnome.ScreenSaver.GetActive")
    w._said_by, w.session_path = "logind", "/org/freedesktop/login1/session/_31"
    assert w._still_said_locked() is False and calls[-1][1] == W.LOGIND
    w._said_by = None
    assert w._still_said_locked() is None
