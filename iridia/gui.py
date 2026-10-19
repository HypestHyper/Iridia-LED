"""Entry point for the Iridia window (GTK 4). The window itself lives in iridia/ui/."""

import os
import sys


def pick_renderer(env=os.environ):
    """GTK's newer renderers (Vulkan, the default on Wayland since GTK 4.16) cut off the tops of letters
    with Iridia's font at fractional scales (Hyprland at 1.25, for one); the GL renderer draws them
    whole. Set before GTK loads; your own GSK_RENDERER still wins (GSK_RENDERER=vulkan iridia-gui)."""
    env.setdefault("GSK_RENDERER", "gl")


def main():
    pick_renderer()
    try:
        import gi
        gi.require_version("Gtk", "4.0")
        from gi.repository import Gtk  # noqa: F401
        import cairo  # noqa: F401
    except (ImportError, ValueError) as e:
        print("Iridia's window needs GTK 4 with Python bindings (PyGObject and pycairo).\n"
              f"  ({e})\n"
              "Install them and run the installer again:\n"
              "  Arch/CachyOS:   sudo pacman -S gtk4 python-gobject python-cairo\n"
              "  Debian/Ubuntu:  sudo apt install gir1.2-gtk-4.0 python3-gi python3-gi-cairo\n"
              "  Fedora:         sudo dnf install gtk4 python3-gobject python3-cairo\n"
              "  openSUSE:       sudo zypper install typelib-1_0-Gtk-4_0 python3-gobject python3-gobject-cairo\n"
              "  Void:           sudo xbps-install gtk4 python3-gobject python3-cairo\n"
              "  Alpine:         sudo apk add gtk4.0 py3-gobject3 py3-cairo",
              file=sys.stderr)
        return 1
    from iridia import i18n
    i18n.setup()                       # before the window's modules load their strings
    from iridia.ui.app import main as run
    return run()


if __name__ == "__main__":
    sys.exit(main())
