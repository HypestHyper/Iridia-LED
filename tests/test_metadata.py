"""The files in data/ (for packagers and validation) match what the installer writes."""
import os
import re

from iridia import APP_ID, VERSION, assets

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(*parts, mode="r"):
    with open(os.path.join(ROOT, *parts), mode) as f:
        return f.read()


def test_desktop_entry_matches_the_installer():
    assert _read("data", f"{APP_ID}.desktop") == assets.desktop_entry()
    assert assets.APP_ID == APP_ID


def test_data_icons_are_the_bundled_ones():
    assert _read("data/icons/hicolor/scalable/apps/iridia.svg", mode="rb") == _read("iridia/data/iridia.svg", mode="rb")
    assert _read("data/icons/hicolor/symbolic/apps/iridia-symbolic.svg", mode="rb") == \
        _read("iridia/data/iridia-symbolic.svg", mode="rb")


def test_every_place_has_the_same_version():
    assert re.search(rf'^version = "{re.escape(VERSION)}"', _read("pyproject.toml"), re.M)
    assert f'<release version="{VERSION}"' in _read("data", f"{APP_ID}.metainfo.xml")
    assert f"pkgver={VERSION}\n" in _read("packaging/arch/PKGBUILD")
    assert f"badge/version-{VERSION}-" in _read("README.md")
