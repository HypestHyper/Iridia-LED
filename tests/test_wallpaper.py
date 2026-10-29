"""Wallpaper detection on the desktops that keep it in settings: a fake HOME and fake commands."""
import os

import pytest

from iridia.wallpaper import WallpaperDetector


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")

    def tool(name, script):
        p = bin_dir / name
        p.write_text("#!/bin/sh\n" + script)
        p.chmod(0o755)

    def image(rel):
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"img")
        return str(p)
    return tmp_path, tool, image


def test_kde_plasma_5_and_6(home):
    tmp, tool, image = home
    pic = image("Pictures/My pic.jpg")
    (tmp / ".config").mkdir()
    (tmp / ".config/plasma-org.kde.plasma.desktop-appletsrc").write_text(
        "[Containments][2]\nplugin=org.kde.panel\n\n"
        "[Containments][2][Applets][5][Configuration][General]\nImage=/not/a/wallpaper.png\n\n"
        "[Containments][7][Wallpaper][org.kde.image][General]\n"
        f"Image=file://{pic.replace(' ', '%20')}\nSlidePaths=/usr/share/wallpapers/\n")
    assert WallpaperDetector()._kde() == pic
    # a wallpaper package (the default ones are): its biggest image
    image("pkg/Next/contents/images/1920x1080.png")
    big = image("pkg/Next/contents/images/5120x2880.png")
    (tmp / ".config/plasma-org.kde.plasma.desktop-appletsrc").write_text(
        f"[Containments][1][Wallpaper][org.kde.image][General]\nImage={tmp}/pkg/Next/\n")
    assert WallpaperDetector()._kde() == big


def test_kde_default_wallpaper_before_one_is_picked(home, monkeypatch):
    tmp, tool, image = home
    data = tmp / "share"
    monkeypatch.setenv("XDG_DATA_DIRS", str(data))
    monkeypatch.setenv("XDG_CONFIG_DIRS", str(tmp / "xdg"))
    next_big = image("share/wallpapers/Next/contents/images/3840x2160.png")
    (tmp / ".config").mkdir()
    rc = tmp / ".config/plasma-org.kde.plasma.desktop-appletsrc"
    rc.write_text("[Containments][1]\nplugin=org.kde.plasma.folder\nwallpaperplugin=org.kde.image\n")
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")
    assert WallpaperDetector()._kde() == next_big            # no Image= line yet: Plasma's own default
    # a distribution's global theme names its own
    theme = image("share/wallpapers/Distro/contents/images/2560x1440.jpg")
    (tmp / "xdg").mkdir()
    (tmp / "xdg/kdeglobals").write_text("[KDE]\nLookAndFeelPackage=org.distro.desktop\n")
    lnf = data / "plasma/look-and-feel/org.distro.desktop/contents"
    lnf.mkdir(parents=True)
    (lnf / "defaults").write_text("[kdeglobals][KDE]\nwidgetStyle=Breeze\n\n[Wallpaper]\nImage=Distro\n")
    assert WallpaperDetector()._kde() == theme
    # a slideshow or a plain colour: no image to guess
    rc.write_text("[Containments][1]\nwallpaperplugin=org.kde.slideshow\n")
    assert WallpaperDetector()._kde() is None
    # and outside Plasma, an installed Plasma's default isn't your wallpaper
    rc.write_text("[Containments][1]\nwallpaperplugin=org.kde.image\n")
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "Hyprland")
    assert WallpaperDetector()._kde() is None


def test_gnome_dark_style_and_slideshows(home):
    tmp, tool, image = home
    light, dark = image("light.png"), image("dark.png")
    xml = tmp / "timed.xml"
    xml.write_text(f"<background><static><duration>1</duration><file>{dark}</file></static></background>")
    tool("gsettings", f"""case "$3" in
  color-scheme) echo "'prefer-dark'" ;;
  picture-uri) echo "'file://{light}'" ;;
  picture-uri-dark) echo "'file://{xml}'" ;;
esac""")
    assert WallpaperDetector()._gnome() == dark
    tool("gsettings", f"""case "$3" in
  color-scheme) exit 1 ;;
  picture-uri) echo "'file://{light}'" ;;
esac""")                                       # GNOME 41 and older: no color-scheme key
    assert WallpaperDetector()._gnome() == light


def test_xfce_uses_the_real_monitor_names(home):
    tmp, tool, image = home
    pic = image("x.jpg")
    tool("xfconf-query", f"""if [ "$3" = -l ]; then
  printf '/backdrop/screen0/monitoreDP-1/workspace1/last-image\\n/backdrop/screen0/monitoreDP-1/workspace0/last-image\\n'
elif [ "$4" = /backdrop/screen0/monitoreDP-1/workspace0/last-image ]; then echo {pic}
else echo /gone.png; fi""")
    assert WallpaperDetector()._xfce() == pic


def test_mate_cosmic_lxqt(home):
    tmp, tool, image = home
    pic = image("m.png")
    tool("gsettings", f'[ "$2" = org.mate.background ] && echo "\'{pic}\'"')
    assert WallpaperDetector()._mate() == pic
    c = tmp / ".config/cosmic/com.system76.CosmicBackground/v1"
    c.mkdir(parents=True)
    (c / "all").write_text(f'(output: "all", source: Path("{pic}"), filter_by_theme: true, rotation_frequency: 300)')
    assert WallpaperDetector()._cosmic() == pic
    q = tmp / ".config/pcmanfm-qt/lxqt"
    q.mkdir(parents=True)
    (q / "settings.conf").write_text(f"[Desktop]\nWallpaperMode=stretch\nWallpaper={pic}\n")
    assert WallpaperDetector()._lxqt() == pic


def test_settings_files_are_watched_instead_of_polled(home):
    tmp, tool, image = home
    d = WallpaperDetector()
    assert d.watch_files() == []                        # nothing remembered yet: nothing to watch
    d._sticky = "gnome"
    assert d.watch_files() == [str(tmp / ".config" / "dconf" / "user")]
    d._sticky = "kde"
    assert str(tmp / ".config/plasma-org.kde.plasma.desktop-appletsrc") in d.watch_files()
    d.set_watched(True)
    assert d.slow_interval == WallpaperDetector.WATCHED_SLOW_SEC
    d.set_watched(False)
    assert d.slow_interval == 3.0


def test_desktop_comes_before_another_sessions_leftovers(home, monkeypatch):
    """Hyprland with caelestia one day, Plasma the next: caelestia's state file still names the
    old wallpaper, but on Plasma, Plasma says what's shown."""
    tmp, tool, image = home
    old, new = image("old.png"), image("new.png")
    state = tmp / ".local/state/caelestia/wallpaper"
    state.mkdir(parents=True)
    (state / "path.txt").write_text(old)
    (tmp / ".config").mkdir()
    (tmp / ".config/plasma-org.kde.plasma.desktop-appletsrc").write_text(
        f"[Containments][1][Wallpaper][org.kde.image][General]\nImage=file://{new}\n")
    cache = tmp / ".config/iridia/detection_cache.json"
    cache.parent.mkdir(parents=True)
    cache.write_text('{"backend": "caelestia"}')
    tool("ps", "echo /usr/bin/plasmashell")
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")
    assert WallpaperDetector(cache_path=str(cache)).detect() == new
    assert '"kde"' in cache.read_text()
    # a service started without the desktop's name: plasmashell running says it
    monkeypatch.delenv("XDG_CURRENT_DESKTOP")
    monkeypatch.delenv("HYPRLAND_INSTANCE_SIGNATURE", raising=False)
    cache.write_text('{"backend": "caelestia"}')
    assert WallpaperDetector(cache_path=str(cache)).detect() == new
    # on Hyprland, caelestia still wins
    tool("ps", "printf '/usr/bin/Hyprland\\n/usr/bin/plasmashell\\n'")
    cache.write_text('{"backend": "caelestia"}')
    assert WallpaperDetector(cache_path=str(cache)).detect() == old
