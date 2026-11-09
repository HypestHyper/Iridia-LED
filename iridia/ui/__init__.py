"""The window. Every library version it uses is fixed here, before any of its modules imports one,
so a system with GTK 3 next to GTK 4 never hands it the wrong Gdk (and PyGObject doesn't warn)."""
try:
    import gi

    for _lib, _ver in (("Gtk", "4.0"), ("Gdk", "4.0"), ("Pango", "1.0")):
        gi.require_version(_lib, _ver)
except (ImportError, ValueError):
    pass                    # no GTK 4: gui.py says what to install
